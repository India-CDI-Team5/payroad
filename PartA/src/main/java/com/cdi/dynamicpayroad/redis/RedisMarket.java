package com.cdi.dynamicpayroad.redis;

import com.cdi.dynamicpayroad.domain.Deal;
import com.cdi.dynamicpayroad.domain.DealCommand;
import com.cdi.dynamicpayroad.domain.DealRules;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.lettuce.core.GeoArgs;
import io.lettuce.core.GeoSearch;
import io.lettuce.core.GeoWithin;
import io.lettuce.core.api.sync.RedisCommands;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * The one Java gateway to the bargaining rules (api-spec §6.6): every call is one Lua script run,
 * which reads, decides and writes atomically. The live service and the experiment runner both
 * go through here, with their own clock passed as {@code now}. No Spring here.
 */
public final class RedisMarket {

    /** A deal as get_deal.lua returns it, plus the display-only meta it was created with. */
    public record DealSnapshot(Deal deal, Map<String, Object> meta) {}

    private static final int SWEEP_LIMIT = 1000;

    private final RedisCommands<String, String> cmd;
    private final int db;
    private final DealRules rules;
    private final LuaScripts scripts;
    private final LuaResultParser parser;
    private final ObjectMapper json = new ObjectMapper();

    public RedisMarket(RedisCommands<String, String> cmd, int db, DealRules rules) {
        this.cmd = cmd;
        this.db = db;
        this.rules = rules;
        this.scripts = new LuaScripts(cmd);
        this.parser = new LuaResultParser(json);
    }

    public DealRules rules() {
        return rules;
    }

    /** create_deal.lua: a new OPEN deal with the rule values copied in, and the rider's presence. */
    public void createDeal(String dealId, String riderId, double originLat, double originLng, double basePrice,
                           Map<String, Object> meta, Instant now) {
        String metaJson;
        try {
            metaJson = json.writeValueAsString(meta);
        } catch (JsonProcessingException e) {
            throw new IllegalArgumentException("meta is not JSON-serialisable", e);
        }
        MarketOutcome r = parser.outcome(scripts.call("create_deal", ms(now), dealId, riderId,
                d(originLat), d(originLng), d(basePrice),
                Long.toString(rules.dealTtl().toMillis()), Long.toString(rules.offerTtl().toMillis()),
                Integer.toString(rules.roundLimit()), d(rules.bandMinRatio()), d(rules.bandMaxRatio()),
                d(rules.avgSpeedKmh()), d(rules.detourFactor()), Integer.toString(rules.maxActiveBids()),
                Long.toString(rules.presenceTtl().toMillis()), metaJson));
        if (!r.ok()) throw new IllegalStateException("create_deal refused: " + r.code() + " " + r.message());
    }

    /** One command on one deal; the script is chosen by the command type. */
    public MarketOutcome apply(String dealId, DealCommand command, Instant now) {
        String reply = switch (command) {
            case DealCommand.PlaceBid c -> scripts.call("place_bid", ms(now), dealId, id(c.driverId()),
                    d(c.price()), d(c.driverLat()), d(c.driverLng()), v(c.version()));
            case DealCommand.WithdrawBid c -> scripts.call("withdraw_bid", ms(now), dealId, id(c.driverId()),
                    v(c.version()));
            case DealCommand.PostOffer c -> scripts.call("post_offer", ms(now), dealId, id(c.riderId()),
                    d(c.price()), v(c.version()));
            case DealCommand.AcceptBid c -> scripts.call("accept_bid", ms(now), dealId, id(c.riderId()),
                    id(c.bidId()), v(c.version()));
            case DealCommand.AcceptOffer c -> scripts.call("accept_offer", ms(now), dealId, id(c.driverId()),
                    v(c.version()));
            case DealCommand.Cancel c -> scripts.call("cancel_deal", ms(now), dealId, id(c.riderId()));
        };
        return parser.outcome(reply);
    }

    /** sweep.lua (§6.5): deal TTL, offer TTL, physical deletion; up to 1,000 per step. */
    public MarketOutcome sweep(Instant now) {
        return parser.outcome(scripts.call("sweep", ms(now), Integer.toString(SWEEP_LIMIT),
                Long.toString(rules.presenceTtl().toMillis())));
    }

    /** get_deal.lua. Empty once the deal was never created or has been purged. */
    public Optional<DealSnapshot> snapshot(String dealId, Instant now) {
        JsonNode root = parser.tree(scripts.call("get_deal", ms(now), dealId));
        if (!root.path("ok").asBoolean(false)) return Optional.empty();
        JsonNode deal = root.get("deal");
        return Optional.of(new DealSnapshot(parser.deal(deal), parser.meta(deal)));
    }

    /**
     * presence_upsert.lua: register or heartbeat a DRIVER or RIDER. Coordinates may be null.
     *
     * @return ONLINE or MATCHED, or null when refused (a driver's first registration without a position)
     */
    public String upsertPresence(String actorType, String actorId, Double lat, Double lng, Duration ttl, Instant now) {
        JsonNode root = parser.tree(scripts.call("presence_upsert", ms(now), actorType, actorId,
                Long.toString(ttl.toMillis()), lat == null ? "" : d(lat), lng == null ? "" : d(lng)));
        return root.path("ok").asBoolean(false) ? root.path("status").asText() : null;
    }

    /**
     * Read-only driver status (§4.5): MATCHED when driver:{id}:state says so, ONLINE while the
     * presence has not expired, otherwise OFFLINE. Does not extend the presence.
     */
    public String driverStatus(String driverId, Instant now) {
        if ("MATCHED".equals(cmd.hget("driver:" + driverId + ":state", "status"))) return "MATCHED";
        String exp = cmd.hget("presence:driver:" + driverId, "expiresAt");
        return exp != null && Long.parseLong(exp) > now.toEpochMilli() ? "ONLINE" : "OFFLINE";
    }

    /**
     * presence_remove.lua: log a DRIVER or RIDER off unless engaged (§1.5, R5).
     *
     * @return true when the presence was removed, false when the actor is engaged and stays
     */
    public boolean removePresence(String actorType, String actorId, Instant now) {
        JsonNode root = parser.tree(scripts.call("presence_remove", ms(now), actorType, id(actorId)));
        return root.path("removed").asBoolean(false);
    }

    /** GEOSEARCH key FROMLONLAT lng lat BYRADIUS radiusKm km: how many members lie within the radius. */
    public int countNearby(String geoKey, double lat, double lng, double radiusKm) {
        return cmd.geosearch(geoKey, GeoSearch.fromCoordinates(lng, lat),
                GeoSearch.byRadius(radiusKm, GeoArgs.Unit.km)).size();
    }

    /** GEOSEARCH geo:deals FROMLONLAT lng lat BYRADIUS radiusKm km ASC COUNT limit: deal ids, nearest first (§4.4). */
    public List<String> nearbyDeals(double lat, double lng, double radiusKm, int limit) {
        return cmd.geosearch("geo:deals", GeoSearch.fromCoordinates(lng, lat),
                        GeoSearch.byRadius(radiusKm, GeoArgs.Unit.km), new GeoArgs().withCount(limit).asc())
                .stream().map(GeoWithin::getMember).toList();
    }

    /** Wipes this market's DB. Refused on DB 0, the live service's. */
    public void flushDb() {
        if (db == 0) throw new IllegalStateException("FLUSHDB refused on DB 0 (live service)");
        cmd.flushdb();
    }

    private static String ms(Instant now) {
        return Long.toString(now.toEpochMilli());
    }

    private static String d(double x) {
        return Double.toString(x);
    }

    /** A missing id is sent as "", which the scripts never accept as an actor. */
    private static String id(String s) {
        return s == null ? "" : s;
    }

    /** "" = no version: skip the check (§5.2). */
    private static String v(Long version) {
        return version == null ? "" : Long.toString(version);
    }
}
