package com.cdi.dynamicpayroad.deal;

import com.cdi.dynamicpayroad.model.Location;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Walking skeleton of the bargaining flow: create deal -> bid -> rider accepts -> MATCHED.
 * In-memory (no Redis yet) and deliberately unvalidated: R1/R2/R6/R8/R9/R11, version CAS and
 * error events are NOT enforced. The goal is to prove the API contract works end to end.
 */
@Service
public class DealService {

    private static final Logger log = LoggerFactory.getLogger(DealService.class);

    // Placeholder pricing until Part B's distance/weather feeds the base price (§4.1).
    private static final double FLAG_PRICE = 30.0;
    private static final double PER_KM_PRICE = 15.0;
    private static final double DETOUR_FACTOR = 1.3;
    private static final double AVG_SPEED_KMH = 20.0;
    private static final double BAND_MIN_RATIO = 0.7;
    private static final double BAND_MAX_RATIO = 3.0;
    private static final Duration DEAL_TTL = Duration.ofMinutes(3);

    private final Map<String, Deal> deals = new ConcurrentHashMap<>();
    private final SimpMessagingTemplate broker;

    public DealService(SimpMessagingTemplate broker) {
        this.broker = broker;
    }

    public Map<String, Object> createDeal(String riderId, Location origin, Location dest) {
        double distanceKm = origin.distanceTo(dest) * DETOUR_FACTOR;
        double durationMin = distanceKm / AVG_SPEED_KMH * 60;
        double basePrice = round2(FLAG_PRICE + PER_KM_PRICE * distanceKm);
        Instant now = Instant.now();

        Deal deal = new Deal("D-" + UUID.randomUUID().toString().substring(0, 6), riderId, origin, dest,
                basePrice, round2(distanceKm), round2(durationMin), now, now.plus(DEAL_TTL));
        deals.put(deal.dealId, deal);
        log.info("DEAL CREATED {} rider={} base={}", deal.dealId, riderId, basePrice);
        return snapshot(deal);
    }

    public Optional<Map<String, Object>> getDeal(String dealId) {
        Deal deal = deals.get(dealId);
        if (deal == null) return Optional.empty();
        synchronized (deal) {
            return Optional.of(snapshot(deal));
        }
    }

    /** Driver places (or replaces) their bid and everyone on the deal topic hears about it. */
    public void placeBid(String dealId, BidMessage msg) {
        Deal deal = deals.get(dealId);
        if (deal == null) {
            log.warn("bid for unknown deal {}", dealId);
            return;
        }
        Map<String, Object> event;
        synchronized (deal) {
            boolean replacing = deal.bidsByDriver.containsKey(msg.driverId());
            double pickupKm = new Location(msg.driverLat(), msg.driverLng()).distanceTo(deal.origin);
            Deal.Bid bid = new Deal.Bid(String.format("B-%03d", deal.nextBidSeq++), msg.driverId(),
                    msg.price(), msg.driverLat(), msg.driverLng(),
                    round2(pickupKm), round2(pickupKm * DETOUR_FACTOR / AVG_SPEED_KMH * 60), Instant.now());
            deal.bidsByDriver.put(msg.driverId(), bid);

            deal.status = Deal.Status.NEGOTIATING;
            deal.pendingSide = "RIDER";
            deal.round++;
            deal.version++;

            event = new LinkedHashMap<>();
            event.put("event", replacing ? "bid.updated" : "bid.placed");
            event.put("dealId", deal.dealId);
            event.put("bid", bidView(bid));
            event.put("lowestBidPrice", deal.lowestBidPrice());
            event.put("bidderCount", deal.bidsByDriver.size());
            event.put("pendingSide", deal.pendingSide);
            event.put("round", deal.round);
            event.put("version", deal.version);
        }
        publish(dealId, event);
    }

    /** Rider picks a specific bid -> that driver wins at that bid's price (path A, §1.4). */
    public void acceptBid(String dealId, AcceptBidMessage msg) {
        Deal deal = deals.get(dealId);
        if (deal == null) {
            log.warn("accept for unknown deal {}", dealId);
            return;
        }
        Map<String, Object> event;
        synchronized (deal) {
            List<Deal.Bid> ranked = deal.bidsAscending();
            Deal.Bid chosen = ranked.stream().filter(b -> b.bidId().equals(msg.bidId())).findFirst().orElse(null);
            if (chosen == null) {
                log.warn("accept of unknown bid {} on deal {}", msg.bidId(), dealId);
                return;
            }
            deal.status = Deal.Status.MATCHED;
            deal.winningBid = chosen;
            deal.matchPath = "RIDER_PICKED_BID";
            deal.chosenRank = ranked.indexOf(chosen) + 1;
            deal.matchedAt = Instant.now();
            deal.version++;

            event = new LinkedHashMap<>();
            event.put("event", "deal.matched");
            event.put("dealId", deal.dealId);
            event.put("driverId", chosen.driverId());
            event.put("finalPrice", chosen.price());
            event.put("matchPath", deal.matchPath);
            event.put("pickupDistanceKm", chosen.pickupDistanceKm());
            event.put("pickupEtaMin", chosen.pickupEtaMin());
            event.put("lowestBidPrice", deal.lowestBidPrice());
            event.put("chosenRank", deal.chosenRank);
            event.put("matchedAt", deal.matchedAt.toString());
            event.put("version", deal.version);
        }
        log.info("DEAL MATCHED {} driver={} price={} rank={}", dealId,
                event.get("driverId"), event.get("finalPrice"), event.get("chosenRank"));
        publish(dealId, event);
    }

    private void publish(String dealId, Map<String, Object> event) {
        broker.convertAndSend("/topic/deal/" + dealId, event);
    }

    private Map<String, Object> snapshot(Deal d) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("dealId", d.dealId);
        m.put("status", d.status.name());
        m.put("basePrice", d.basePrice);
        m.put("priceBand", Map.of("min", round2(d.basePrice * BAND_MIN_RATIO), "max", round2(d.basePrice * BAND_MAX_RATIO)));
        m.put("distanceKm", d.distanceKm);
        m.put("durationMin", d.durationMin);
        m.put("bids", d.bidsAscending().stream().map(DealService::bidView).toList());
        m.put("lowestBidPrice", d.lowestBidPrice());
        m.put("bidderCount", d.bidsByDriver.size());
        m.put("pendingSide", d.pendingSide);
        m.put("round", d.round);
        m.put("version", d.version);
        m.put("createdAt", d.createdAt.toString());
        m.put("expiresAt", d.expiresAt.toString());
        return m;
    }

    private static Map<String, Object> bidView(Deal.Bid b) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("bidId", b.bidId());
        m.put("driverId", b.driverId());
        m.put("price", b.price());
        m.put("driverLat", b.driverLat());
        m.put("driverLng", b.driverLng());
        m.put("pickupDistanceKm", b.pickupDistanceKm());
        m.put("pickupEtaMin", b.pickupEtaMin());
        m.put("createdAt", b.createdAt().toString());
        return m;
    }

    private static double round2(double v) {
        return Math.round(v * 100.0) / 100.0;
    }

    /** STOMP /app/deal/{dealId}/bid payload (§5.2). `version` is accepted but not checked yet. */
    public record BidMessage(String driverId, double price, double driverLat, double driverLng, Long version) {}

    /** STOMP /app/deal/{dealId}/accept-bid payload (§5.2). */
    public record AcceptBidMessage(String riderId, String bidId, Long version) {}
}
