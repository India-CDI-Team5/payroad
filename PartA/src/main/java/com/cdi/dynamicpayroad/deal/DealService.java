package com.cdi.dynamicpayroad.deal;

import com.cdi.dynamicpayroad.domain.Deal;
import com.cdi.dynamicpayroad.domain.DealCommand;
import com.cdi.dynamicpayroad.domain.DealEvent;
import com.cdi.dynamicpayroad.domain.DealRules;
import com.cdi.dynamicpayroad.domain.DealStateMachine;
import com.cdi.dynamicpayroad.domain.Enums.DriverStatus;
import com.cdi.dynamicpayroad.domain.Enums.EndReason;
import com.cdi.dynamicpayroad.domain.ErrorCode;
import com.cdi.dynamicpayroad.domain.MarketStateMachine;
import com.cdi.dynamicpayroad.domain.MarketStateMachine.MarketResult;
import com.cdi.dynamicpayroad.domain.MarketStateMachine.MarketState;
import com.cdi.dynamicpayroad.engine.MatchingEngine;
import com.cdi.dynamicpayroad.model.DealHistory;
import com.cdi.dynamicpayroad.model.Location;
import com.cdi.dynamicpayroad.pool.OnlinePool;
import com.cdi.dynamicpayroad.repository.DealHistoryRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/**
 * Runs the bargaining rules (domain/) for the live service: holds the market, serialises every
 * command under one lock (so R9 and R10 are atomic), broadcasts the resulting events on
 * /topic/deal/{dealId}, and writes a DealHistory row when a deal closes.
 *
 * <p>In memory, single node (plan v4 §3.2). Drivers become ONLINE on their first action until
 * explicit presence arrives (milestone 10/7); a matched driver stays MATCHED (R11).
 */
@Service
public class DealService {

    private static final Logger log = LoggerFactory.getLogger(DealService.class);

    // Placeholder pricing until Part B's /quote provides the base price (milestone 10/5).
    private static final double FLAG_PRICE = 30.0;
    private static final double PER_KM_PRICE = 15.0;
    /** api-spec §6.1: a closed deal stays readable for 300 s after creation, then is dropped. */
    private static final Duration RETENTION = Duration.ofSeconds(300);

    /** What the deal was created with, beyond the domain state. */
    public record Meta(double destLat, double destLng, double distanceKm, double durationMin, int demand, int supply) {}

    /** Result of a REST-style call: the body to return, or the rejection. */
    public record Reply(Map<String, Object> body, ErrorCode error) {
        static Reply ok(Map<String, Object> body) { return new Reply(body, null); }
        static Reply fail(Map<String, Object> error, ErrorCode code) { return new Reply(error, code); }
    }

    private final DealRules rules = DealRules.defaults();
    private final MarketStateMachine machine = new MarketStateMachine(new DealStateMachine(rules));
    private final SimpMessagingTemplate broker;
    private final DealHistoryRepository history;
    private final OnlinePool pool;
    private final MatchingEngine matching;
    private final Clock clock;
    private final String experimentTag;

    private MarketState market = new MarketState(Map.of(), Map.of());
    private final Map<String, Meta> meta = new HashMap<>();

    public DealService(SimpMessagingTemplate broker, DealHistoryRepository history, OnlinePool pool,
                       MatchingEngine matching, Clock clock,
                       @Value("${deal.experiment-tag:live}") String experimentTag) {
        this.broker = broker;
        this.history = history;
        this.pool = pool;
        this.matching = matching;
        this.clock = clock;
        this.experimentTag = experimentTag;
    }

    public DealRules rules() {
        return rules;
    }

    /** §4.1: open a deal at a placeholder base price, with the local demand/supply snapshot. */
    public synchronized Map<String, Object> create(String riderId, double originLat, double originLng,
                                                   double destLat, double destLng) {
        Instant now = clock.instant();
        double distanceKm = new Location(originLat, originLng).distanceTo(new Location(destLat, destLng)) * rules.detourFactor();
        double durationMin = distanceKm / rules.avgSpeedKmh() * 60;
        double basePrice = DealJson.round2(FLAG_PRICE + PER_KM_PRICE * distanceKm);
        MatchingEngine.Outcome local = matching.evaluateAt(new Location(originLat, originLng), pool.users(), pool.waitingDrivers());

        Deal deal = Deal.open("D-" + UUID.randomUUID().toString().substring(0, 8), riderId,
                originLat, originLng, basePrice, now, rules);
        Map<String, Deal> deals = new HashMap<>(market.deals());
        deals.put(deal.dealId(), deal);
        market = new MarketState(deals, market.drivers());
        Meta m = new Meta(destLat, destLng, distanceKm, durationMin, local.demandInRadius(), local.supplyInRadius());
        meta.put(deal.dealId(), m);
        log.info("DEAL CREATED {} rider={} base={}", deal.dealId(), riderId, basePrice);
        return DealJson.snapshot(deal, m, rules);
    }

    /** §4.2. */
    public synchronized Optional<Map<String, Object>> get(String dealId) {
        Deal deal = market.deals().get(dealId);
        return deal == null ? Optional.empty() : Optional.of(DealJson.snapshot(deal, meta.get(dealId), rules));
    }

    /** §4.3: the rider cancels (R12). */
    public synchronized Reply cancel(String dealId, String riderId) {
        if (!market.deals().containsKey(dealId)) return notFound(dealId);
        Map<String, Object> error = apply(dealId, new DealCommand.Cancel(riderId));
        if (error != null) return Reply.fail(error, ErrorCode.valueOf((String) error.get("code")));
        Deal d = market.deals().get(dealId);
        return Reply.ok(Map.of("dealId", dealId, "status", d.status().name(), "version", d.version()));
    }

    /**
     * §5.2: a STOMP command. Events go to everyone on the deal topic; the return value is the
     * error event for the sender alone, or null when the command was accepted.
     */
    public synchronized Map<String, Object> handle(String dealId, DealCommand command) {
        if (!market.deals().containsKey(dealId)) {
            return DealJson.error(dealId, ErrorCode.DEAL_NOT_ACTIVE, "거래가 없습니다", 0);
        }
        return apply(dealId, command);
    }

    /** R6/R7 on every open deal, and drop closed deals past the retention window. Called every second. */
    public synchronized void tick() {
        Instant now = clock.instant();
        for (Deal d : List.copyOf(market.deals().values())) {
            if (d.status().isActive()) {
                apply(d.dealId(), new DealCommand.Tick());
            } else if (!now.isBefore(d.createdAt().plus(RETENTION))) {
                Map<String, Deal> deals = new HashMap<>(market.deals());
                deals.remove(d.dealId());
                market = new MarketState(deals, market.drivers());
                meta.remove(d.dealId());
            }
        }
    }

    // --- internals (always called under the lock) -----------------------------------------

    private Map<String, Object> apply(String dealId, DealCommand command) {
        Instant now = clock.instant();
        MarketState current = withImplicitPresence(market, command);
        MarketResult result = machine.apply(current, dealId, command, now);
        if (result instanceof MarketResult.Rejected r) {
            return DealJson.error(dealId, r.code(), r.message(), r.version());
        }
        MarketResult.Accepted accepted = (MarketResult.Accepted) result;
        market = accepted.state();

        Map<String, Object> requesterError = null;
        for (Map.Entry<String, List<DealEvent>> entry : accepted.events().entrySet()) {
            for (DealEvent e : entry.getValue()) {
                broker.convertAndSend("/topic/deal/" + entry.getKey(), DealJson.event(e));
                if (e instanceof DealEvent.DealMatched || e instanceof DealEvent.DealExpired) {
                    record(market.deals().get(entry.getKey()), now);
                }
                // R8: the action that hit the round limit closed the deal instead of counting.
                if (e instanceof DealEvent.DealExpired x && x.reason() == EndReason.ROUND_LIMIT
                        && entry.getKey().equals(dealId) && !(command instanceof DealCommand.Tick)) {
                    requesterError = DealJson.error(dealId, ErrorCode.ROUND_LIMIT_EXCEEDED,
                            "라운드 상한(" + rules.roundLimit() + "회)을 넘어 거래가 종료되었습니다", x.version());
                }
            }
        }
        return requesterError;
    }

    /** Until presence endpoints exist, a driver who acts is online unless already MATCHED. */
    private static MarketState withImplicitPresence(MarketState market, DealCommand command) {
        String driver = switch (command) {
            case DealCommand.PlaceBid c -> c.driverId();
            case DealCommand.WithdrawBid c -> c.driverId();
            case DealCommand.AcceptOffer c -> c.driverId();
            default -> null;
        };
        if (driver == null || market.drivers().containsKey(driver)) return market;
        Map<String, DriverStatus> drivers = new HashMap<>(market.drivers());
        drivers.put(driver, DriverStatus.ONLINE);
        return new MarketState(market.deals(), drivers);
    }

    private void record(Deal deal, Instant closedAt) {
        Meta m = meta.get(deal.dealId());
        history.save(DealHistory.closed(deal, m.demand(), m.supply(), deal.lastBidByDriver().size(),
                experimentTag, null, closedAt));
        log.info("DEAL CLOSED {} status={} reason={} price={}", deal.dealId(), deal.status(),
                deal.endReason(), deal.match() == null ? null : deal.match().finalPrice());
    }

    private static Reply notFound(String dealId) {
        return Reply.fail(DealJson.error(dealId, ErrorCode.DEAL_NOT_ACTIVE, "거래가 없습니다", 0), null);
    }
}
