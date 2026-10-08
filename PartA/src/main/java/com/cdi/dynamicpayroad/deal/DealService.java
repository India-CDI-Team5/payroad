package com.cdi.dynamicpayroad.deal;

import com.cdi.dynamicpayroad.domain.Deal;
import com.cdi.dynamicpayroad.domain.DealCommand;
import com.cdi.dynamicpayroad.domain.DealEvent;
import com.cdi.dynamicpayroad.domain.DealRules;
import com.cdi.dynamicpayroad.domain.ErrorCode;
import com.cdi.dynamicpayroad.domain.Geo;
import com.cdi.dynamicpayroad.engine.MatchingEngine;
import com.cdi.dynamicpayroad.model.DealHistory;
import com.cdi.dynamicpayroad.model.Location;
import com.cdi.dynamicpayroad.pool.OnlinePool;
import com.cdi.dynamicpayroad.redis.MarketOutcome;
import com.cdi.dynamicpayroad.redis.RedisMarket;
import com.cdi.dynamicpayroad.redis.RedisMarket.DealSnapshot;
import com.cdi.dynamicpayroad.repository.DealHistoryRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/**
 * Runs the bargaining rules for the live service. Holds no state: every command is one Lua script
 * on Redis (redis/RedisMarket), which makes R9 and R10 atomic. The resulting events go out on
 * /topic/deal/{dealId}, and each deal the script closed gets a DealHistory row.
 */
@Service
public class DealService {

    private static final Logger log = LoggerFactory.getLogger(DealService.class);

    // Placeholder pricing until Part B's /quote provides the base price (milestone 10/5).
    private static final double FLAG_PRICE = 30.0;
    private static final double PER_KM_PRICE = 15.0;
    private static final Duration IMPLICIT_PRESENCE_TTL = Duration.ofSeconds(60);

    /** Result of a REST-style call. {@code error} is set only when {@code outcome} is REJECTED. */
    public record Reply(Outcome outcome, Map<String, Object> body, ErrorCode error) {
        public enum Outcome { OK, NOT_FOUND, REJECTED }
    }

    private final SimpMessagingTemplate broker;
    private final DealHistoryRepository history;
    private final OnlinePool pool;
    private final MatchingEngine matching;
    private final RedisMarket redisMarket;
    private final Clock clock;
    private final String experimentTag;

    public DealService(SimpMessagingTemplate broker, DealHistoryRepository history, OnlinePool pool,
                       MatchingEngine matching, RedisMarket redisMarket, Clock clock,
                       @Value("${deal.experiment-tag:live}") String experimentTag) {
        this.broker = broker;
        this.history = history;
        this.pool = pool;
        this.matching = matching;
        this.redisMarket = redisMarket;
        this.clock = clock;
        this.experimentTag = experimentTag;
    }

    /** §4.1: open a deal at a placeholder base price, with the local demand/supply snapshot. */
    public Map<String, Object> create(String riderId, double originLat, double originLng,
                                      double destLat, double destLng) {
        Instant now = clock.instant();
        DealRules rules = redisMarket.rules();
        double distanceKm = Geo.haversineKm(originLat, originLng, destLat, destLng) * rules.detourFactor();
        double durationMin = distanceKm / rules.avgSpeedKmh() * 60;
        double basePrice = DealJson.round2(FLAG_PRICE + PER_KM_PRICE * distanceKm);
        MatchingEngine.Outcome local = matching.evaluateAt(new Location(originLat, originLng), pool.users(), pool.waitingDrivers());

        String dealId = "D-" + UUID.randomUUID().toString().substring(0, 8);
        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("destLat", destLat);
        meta.put("destLng", destLng);
        meta.put("distanceKm", distanceKm);
        meta.put("durationMin", durationMin);
        meta.put("demand", local.demandInRadius());
        meta.put("supply", local.supplyInRadius());
        redisMarket.createDeal(dealId, riderId, originLat, originLng, basePrice, meta, now);
        log.info("DEAL CREATED {} rider={} base={}", dealId, riderId, basePrice);
        DealSnapshot snapshot = redisMarket.snapshot(dealId, now)
                .orElseThrow(() -> new IllegalStateException("deal vanished right after creation: " + dealId));
        return DealJson.snapshot(snapshot, rules);
    }

    /** §4.2. Empty once the deal has been purged (300 s after creation). */
    public Optional<Map<String, Object>> get(String dealId) {
        return redisMarket.snapshot(dealId, clock.instant()).map(s -> DealJson.snapshot(s, redisMarket.rules()));
    }

    /** §4.3: the rider cancels (R12). */
    public Reply cancel(String dealId, String riderId) {
        Instant now = clock.instant();
        MarketOutcome r = redisMarket.apply(dealId, new DealCommand.Cancel(riderId), now);
        if (!r.ok()) {
            Map<String, Object> error = DealJson.error(dealId, r.code(), r.message(), r.version());
            // The script reports a missing deal as DEAL_NOT_ACTIVE with version 0.
            if (r.code() == ErrorCode.DEAL_NOT_ACTIVE && r.version() == 0) {
                return new Reply(Reply.Outcome.NOT_FOUND, error, null);
            }
            return new Reply(Reply.Outcome.REJECTED, error, r.code());
        }
        publish(r);
        Deal d = redisMarket.snapshot(dealId, now).orElseThrow().deal();
        return new Reply(Reply.Outcome.OK, Map.of("dealId", dealId, "status", d.status().name(), "version", d.version()), null);
    }

    /**
     * §5.2: a STOMP command. Events go to everyone on the deal topic; the return value is the
     * error event for the sender alone, or null when the command was accepted.
     */
    public Map<String, Object> handle(String dealId, DealCommand command) {
        Instant now = clock.instant();
        implicitPresence(dealId, command, now);   // A3에서 제거: 암묵적 presence
        MarketOutcome r = redisMarket.apply(dealId, command, now);
        if (!r.ok()) {
            return DealJson.error(dealId, r.code(), r.message(), r.version());
        }
        publish(r);
        // R8: the action that hit the round limit closed the deal instead of counting.
        if (r.requesterErrorCode() != null) {
            return DealJson.error(dealId, r.requesterErrorCode(), r.requesterErrorMessage(), r.requesterErrorVersion());
        }
        return null;
    }

    /** §6.5: sweep.lua once (deal TTL, offer TTL, physical deletion). Called every second. */
    public void sweep() {
        publish(redisMarket.sweep(clock.instant()));
    }

    // --- internals ---------------------------------------------------------------------------

    private void publish(MarketOutcome r) {
        for (Map.Entry<String, List<DealEvent>> entry : r.events().entrySet()) {
            for (DealEvent e : entry.getValue()) {
                broker.convertAndSend("/topic/deal/" + entry.getKey(), DealJson.event(e));
            }
        }
        for (String dealId : r.closed()) {
            Optional<DealSnapshot> s = redisMarket.snapshot(dealId, r.closedAt());
            if (s.isPresent()) {
                record(s.get(), r.closedAt());
            } else {
                // sweep.lua closes and purges in one call when a deal reaches its purge time still open.
                log.warn("DEAL CLOSED {} but already purged; no DealHistory row", dealId);
            }
        }
    }

    // A3에서 제거: 암묵적 presence
    /** Until presence endpoints exist, a driver who acts is registered (60 s) at the bid position or the deal origin. */
    private void implicitPresence(String dealId, DealCommand command, Instant now) {
        String driver;
        Double lat = null;
        Double lng = null;
        switch (command) {
            case DealCommand.PlaceBid c -> {
                driver = c.driverId();
                lat = c.driverLat();
                lng = c.driverLng();
            }
            case DealCommand.WithdrawBid c -> driver = c.driverId();
            case DealCommand.AcceptOffer c -> driver = c.driverId();
            default -> driver = null;
        }
        if (driver == null || driver.isEmpty()) return;
        if (lat == null) {
            Optional<DealSnapshot> s = redisMarket.snapshot(dealId, now);
            if (s.isEmpty()) return;
            lat = s.get().deal().originLat();
            lng = s.get().deal().originLng();
        }
        redisMarket.upsertPresence("DRIVER", driver, lat, lng, IMPLICIT_PRESENCE_TTL, now);
    }

    private void record(DealSnapshot s, Instant closedAt) {
        Deal deal = s.deal();
        history.save(DealHistory.closed(deal, intMeta(s.meta(), "demand"), intMeta(s.meta(), "supply"),
                deal.lastBidByDriver().size(), experimentTag, null, closedAt));
        log.info("DEAL CLOSED {} status={} reason={} price={}", deal.dealId(), deal.status(),
                deal.endReason(), deal.match() == null ? null : deal.match().finalPrice());
    }

    private static int intMeta(Map<String, Object> meta, String key) {
        Object v = meta.get(key);
        return v instanceof Number n ? n.intValue() : 0;
    }
}
