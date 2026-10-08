package com.cdi.dynamicpayroad.redis;

import com.cdi.dynamicpayroad.domain.Deal;
import com.cdi.dynamicpayroad.domain.DealEvent;
import com.cdi.dynamicpayroad.domain.DealStatus;
import com.cdi.dynamicpayroad.domain.Enums.EndReason;
import com.cdi.dynamicpayroad.domain.Enums.MatchPath;
import com.cdi.dynamicpayroad.domain.Enums.PendingSide;
import com.cdi.dynamicpayroad.domain.Enums.WithdrawReason;
import com.cdi.dynamicpayroad.domain.ErrorCode;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Turns the JSON replies of the Lua scripts into Java values (api-spec §6.6).
 * Real numbers arrive as '%.17g' strings, times as epoch-ms numbers. cjson writes an empty
 * Lua table as {} (read here as an empty list) and leaves nil fields out (read as null).
 */
public final class LuaResultParser {

    private final ObjectMapper json;

    public LuaResultParser(ObjectMapper json) {
        this.json = json;
    }

    public LuaResultParser() {
        this(new ObjectMapper());
    }

    /** A command or sweep reply. */
    public MarketOutcome outcome(String reply) {
        JsonNode root = tree(reply);
        if (!root.path("ok").asBoolean(false)) {
            return new MarketOutcome(false, ErrorCode.valueOf(root.path("code").asText()), text(root, "message"),
                    root.path("version").asLong(0), new LinkedHashMap<>(), List.of(), null, null, null, 0);
        }
        LinkedHashMap<String, List<DealEvent>> events = new LinkedHashMap<>();
        for (JsonNode e : list(root.get("events"))) {
            DealEvent event = event(e);
            events.computeIfAbsent(event.dealId(), k -> new ArrayList<>()).add(event);
        }
        List<String> closed = new ArrayList<>();
        for (JsonNode id : list(root.get("closed"))) closed.add(id.asText());
        JsonNode err = root.get("requesterError");
        boolean hasErr = err != null && err.isObject();
        return new MarketOutcome(true, null, null, 0, events, List.copyOf(closed), instant(root, "closedAt"),
                hasErr ? ErrorCode.valueOf(err.path("code").asText()) : null,
                hasErr ? text(err, "message") : null,
                hasErr ? err.path("version").asLong(0) : 0);
    }

    /** The {@code deal} object of a get_deal reply. */
    public Deal deal(JsonNode d) {
        List<Deal.Bid> bids = new ArrayList<>();
        for (JsonNode b : list(d.get("bids"))) bids.add(bid(b));

        Map<String, Double> lastBid = new LinkedHashMap<>();
        JsonNode last = d.get("lastBid");
        if (last != null && last.isObject()) {
            for (Iterator<Map.Entry<String, JsonNode>> it = last.fields(); it.hasNext(); ) {
                Map.Entry<String, JsonNode> e = it.next();
                lastBid.put(e.getKey(), Double.parseDouble(e.getValue().asText()));
            }
        }

        Deal.RiderOffer offer = d.hasNonNull("offerPrice")
                ? new Deal.RiderOffer(dbl(d, "offerPrice"), instant(d, "offerCreatedAt"), instant(d, "offerExpiresAt"))
                : null;
        Deal.Match match = d.hasNonNull("matchDriverId")
                ? new Deal.Match(text(d, "matchDriverId"), dbl(d, "finalPrice"),
                        MatchPath.valueOf(text(d, "matchPath")), d.path("chosenRank").asInt(),
                        dblOrNull(d, "matchLowestBidPrice"), dblOrNull(d, "winningPickupDistanceKm"),
                        dblOrNull(d, "winningPickupEtaMin"), dblOrNull(d, "lowestBidPickupDistanceKm"),
                        dblOrNull(d, "lowestBidPickupEtaMin"), instant(d, "matchedAt"))
                : null;
        String endReason = text(d, "endReason");

        return new Deal(text(d, "dealId"), text(d, "riderId"), dbl(d, "originLat"), dbl(d, "originLng"),
                dbl(d, "basePrice"), instant(d, "createdAt"), instant(d, "expiresAt"),
                DealStatus.valueOf(text(d, "status")), PendingSide.valueOf(text(d, "pendingSide")),
                d.path("round").asInt(), d.path("version").asLong(), bids, lastBid, offer,
                dblOrNull(d, "lastOfferPrice"), d.path("withdrawCount").asInt(), d.path("nextBidSeq").asInt(),
                match, endReason == null ? null : EndReason.valueOf(endReason));
    }

    /** The {@code meta} JSON string the deal was created with, as a map (empty when absent). */
    public Map<String, Object> meta(JsonNode d) {
        String raw = text(d, "meta");
        if (raw == null || raw.isEmpty()) return new LinkedHashMap<>();
        try {
            return json.readValue(raw, new TypeReference<LinkedHashMap<String, Object>>() {});
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("bad meta JSON: " + raw, e);
        }
    }

    public JsonNode tree(String reply) {
        try {
            return json.readTree(reply);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("bad Lua reply: " + reply, e);
        }
    }

    private DealEvent event(JsonNode e) {
        String dealId = text(e, "dealId");
        long version = e.path("version").asLong();
        String name = text(e, "event");
        return switch (name) {
            case "bid.placed" -> new DealEvent.BidPlaced(dealId, bid(e.get("bid")), dblOrNull(e, "lowestBidPrice"),
                    e.path("bidderCount").asInt(), PendingSide.valueOf(text(e, "pendingSide")),
                    e.path("round").asInt(), version);
            case "bid.updated" -> new DealEvent.BidUpdated(dealId, bid(e.get("bid")), dblOrNull(e, "lowestBidPrice"),
                    e.path("bidderCount").asInt(), PendingSide.valueOf(text(e, "pendingSide")),
                    e.path("round").asInt(), version);
            case "bid.withdrawn" -> new DealEvent.BidWithdrawn(dealId, text(e, "bidId"), text(e, "driverId"),
                    WithdrawReason.valueOf(text(e, "reason")), dblOrNull(e, "lowestBidPrice"),
                    e.path("bidderCount").asInt(), e.path("round").asInt(), version);
            case "offer.posted" -> new DealEvent.OfferPosted(dealId, dbl(e, "price"), instant(e, "expiresAt"),
                    PendingSide.valueOf(text(e, "pendingSide")), e.path("round").asInt(), version);
            case "offer.expired" -> new DealEvent.OfferExpired(dealId, PendingSide.valueOf(text(e, "pendingSide")),
                    e.path("round").asInt(), version);
            case "deal.matched" -> new DealEvent.DealMatched(dealId, new Deal.Match(text(e, "driverId"),
                    dbl(e, "finalPrice"), MatchPath.valueOf(text(e, "matchPath")), e.path("chosenRank").asInt(),
                    dblOrNull(e, "lowestBidPrice"), dblOrNull(e, "pickupDistanceKm"), dblOrNull(e, "pickupEtaMin"),
                    dblOrNull(e, "lowestBidPickupDistanceKm"), dblOrNull(e, "lowestBidPickupEtaMin"),
                    instant(e, "matchedAt")), version);
            case "deal.expired" -> new DealEvent.DealExpired(dealId, EndReason.valueOf(text(e, "reason")), version);
            default -> throw new IllegalStateException("unknown event: " + name);
        };
    }

    private static Deal.Bid bid(JsonNode b) {
        return new Deal.Bid(text(b, "bidId"), text(b, "driverId"), dbl(b, "price"), dbl(b, "driverLat"),
                dbl(b, "driverLng"), dbl(b, "pickupDistanceKm"), dbl(b, "pickupEtaMin"), instant(b, "createdAt"));
    }

    /** cjson writes an empty table as {}: treat anything that is not an array as empty. */
    private static List<JsonNode> list(JsonNode node) {
        List<JsonNode> out = new ArrayList<>();
        if (node != null && node.isArray()) node.forEach(out::add);
        return out;
    }

    private static String text(JsonNode n, String field) {
        JsonNode v = n.get(field);
        return v == null || v.isNull() ? null : v.asText();
    }

    private static Double dblOrNull(JsonNode n, String field) {
        JsonNode v = n.get(field);
        if (v == null || v.isNull()) return null;
        return v.isTextual() ? Double.parseDouble(v.asText()) : v.asDouble();
    }

    private static double dbl(JsonNode n, String field) {
        Double v = dblOrNull(n, field);
        if (v == null) throw new IllegalStateException("missing number: " + field);
        return v;
    }

    private static Instant instant(JsonNode n, String field) {
        JsonNode v = n.get(field);
        if (v == null || v.isNull()) return null;
        return Instant.ofEpochMilli(v.isTextual() ? Long.parseLong(v.asText()) : v.asLong());
    }
}
