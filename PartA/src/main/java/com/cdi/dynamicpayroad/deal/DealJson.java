package com.cdi.dynamicpayroad.deal;

import com.cdi.dynamicpayroad.domain.Deal;
import com.cdi.dynamicpayroad.domain.DealEvent;
import com.cdi.dynamicpayroad.domain.DealRules;
import com.cdi.dynamicpayroad.domain.ErrorCode;

import java.util.LinkedHashMap;
import java.util.Map;

/** Wire shapes of api-spec §4 (REST) and §5.3 (STOMP events): every event carries event, dealId, version. */
final class DealJson {

    private DealJson() {}

    /** §4.1 / §4.2. Route and weather fields stay placeholders until Part B /quote is wired in (milestone 10/5). */
    static Map<String, Object> snapshot(Deal d, DealService.Meta meta, DealRules rules) {
        DealRules.PriceBand band = rules.band(d.basePrice());
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("dealId", d.dealId());
        m.put("status", d.status().name());
        m.put("basePrice", round2(d.basePrice()));
        m.put("priceBand", Map.of("min", round2(band.min()), "max", round2(band.max())));
        m.put("distanceKm", round2(meta.distanceKm()));
        m.put("durationMin", round2(meta.durationMin()));
        m.put("avgRainMm", null);
        m.put("weatherFactor", 1.0);
        m.put("routePolyline", null);
        m.put("bids", d.bidsAscending().stream().map(DealJson::bid).toList());
        m.put("riderOffer", d.offer() == null ? null : Map.of(
                "price", d.offer().price(),
                "createdAt", d.offer().createdAt().toString(),
                "expiresAt", d.offer().expiresAt().toString()));
        m.put("lowestBidPrice", d.lowestBidPrice().isPresent() ? d.lowestBidPrice().getAsDouble() : null);
        m.put("bidderCount", d.bids().size());
        m.put("pendingSide", d.pendingSide().name());
        m.put("round", d.round());
        m.put("version", d.version());
        m.put("createdAt", d.createdAt().toString());
        m.put("expiresAt", d.expiresAt().toString());
        return m;
    }

    static Map<String, Object> bid(Deal.Bid b) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("bidId", b.bidId());
        m.put("driverId", b.driverId());
        m.put("price", b.price());
        m.put("driverLat", b.driverLat());
        m.put("driverLng", b.driverLng());
        m.put("pickupDistanceKm", round2(b.pickupDistanceKm()));
        m.put("pickupEtaMin", round2(b.pickupEtaMin()));
        m.put("createdAt", b.createdAt().toString());
        return m;
    }

    /** §5.3 event bodies. */
    static Map<String, Object> event(DealEvent e) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("event", e.name());
        m.put("dealId", e.dealId());
        switch (e) {
            case DealEvent.BidPlaced x -> bidChange(m, x.bid(), x.lowestBidPrice(), x.bidderCount(), x.pendingSide().name(), x.round());
            case DealEvent.BidUpdated x -> bidChange(m, x.bid(), x.lowestBidPrice(), x.bidderCount(), x.pendingSide().name(), x.round());
            case DealEvent.BidWithdrawn x -> {
                m.put("bidId", x.bidId());
                m.put("driverId", x.driverId());
                m.put("reason", x.reason().name());
                m.put("lowestBidPrice", x.lowestBidPrice());
                m.put("bidderCount", x.bidderCount());
                m.put("round", x.round());
            }
            case DealEvent.OfferPosted x -> {
                m.put("price", x.price());
                m.put("expiresAt", x.expiresAt().toString());
                m.put("pendingSide", x.pendingSide().name());
                m.put("round", x.round());
            }
            case DealEvent.OfferExpired x -> {
                m.put("pendingSide", x.pendingSide().name());
                m.put("round", x.round());
            }
            case DealEvent.DealMatched x -> {
                Deal.Match match = x.match();
                m.put("driverId", match.driverId());
                m.put("finalPrice", match.finalPrice());
                m.put("matchPath", match.matchPath().name());
                m.put("pickupDistanceKm", match.pickupDistanceKm() == null ? null : round2(match.pickupDistanceKm()));
                m.put("pickupEtaMin", match.pickupEtaMin() == null ? null : round2(match.pickupEtaMin()));
                m.put("lowestBidPrice", match.lowestBidPrice());
                m.put("chosenRank", match.chosenRank());
                m.put("matchedAt", match.matchedAt().toString());
            }
            case DealEvent.DealExpired x -> m.put("reason", x.reason().name());
        }
        m.put("version", e.version());
        return m;
    }

    /** §5.3 {@code error}, sent only to the requester. */
    static Map<String, Object> error(String dealId, ErrorCode code, String message, long version) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("event", "error");
        m.put("dealId", dealId);
        m.put("code", code.name());
        m.put("message", message);
        m.put("version", version);
        return m;
    }

    private static void bidChange(Map<String, Object> m, Deal.Bid bid, Double lowest, int bidders, String pending, int round) {
        m.put("bid", bid(bid));
        m.put("lowestBidPrice", lowest);
        m.put("bidderCount", bidders);
        m.put("pendingSide", pending);
        m.put("round", round);
    }

    static double round2(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
