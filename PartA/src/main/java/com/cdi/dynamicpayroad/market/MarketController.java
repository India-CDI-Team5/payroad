package com.cdi.dynamicpayroad.market;

import com.cdi.dynamicpayroad.domain.Deal;
import com.cdi.dynamicpayroad.redis.RedisMarket;
import com.cdi.dynamicpayroad.redis.RedisMarket.DealSnapshot;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * GET /api/market (api-spec §4.4): active deals whose origin is within 10 km, nearest first.
 * Clients poll it every 3 s; /topic/market is not implemented (§5.4).
 */
@RestController
public class MarketController {

    public static final double RADIUS_KM = 10.0;
    static final int CELL_PRECISION = 5;
    /** Height and width of a precision-5 geohash cell in degrees (180 / 2^12 = 360 / 2^13). */
    static final double CELL_DEG = 0.0439;

    private final RedisMarket redisMarket;
    private final Clock clock;

    public MarketController(RedisMarket redisMarket, Clock clock) {
        this.redisMarket = redisMarket;
        this.clock = clock;
    }

    @GetMapping("/api/market")
    public ResponseEntity<Map<String, Object>> market(@RequestParam double lat, @RequestParam double lng,
                                                      @RequestParam(defaultValue = "30") int limit) {
        if (limit < 1) return ResponseEntity.badRequest().body(Map.of("message", "limit must be at least 1"));
        Instant now = clock.instant();
        List<Map<String, Object>> deals = new ArrayList<>();
        for (String dealId : redisMarket.nearbyDeals(lat, lng, RADIUS_KM, limit)) {
            Optional<DealSnapshot> s = redisMarket.snapshot(dealId, now);
            if (s.isPresent() && s.get().deal().status().isActive()) deals.add(summary(s.get()));
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("deals", deals);
        body.put("cells", cells(lat, lng));
        body.put("generatedAt", now.toString());
        return ResponseEntity.ok(body);
    }

    /** The request point's precision-5 geohash first, then the 8 cells around it (duplicates dropped). */
    static List<String> cells(double lat, double lng) {
        LinkedHashSet<String> out = new LinkedHashSet<>();
        out.add(Geohash.encode(lat, lng, CELL_PRECISION));
        double[][] around = {{1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0}, {-1, -1}, {0, -1}, {1, -1}};
        for (double[] d : around) {
            out.add(Geohash.encode(lat + d[0] * CELL_DEG, lng + d[1] * CELL_DEG, CELL_PRECISION));
        }
        return List.copyOf(out);
    }

    private static Map<String, Object> summary(DealSnapshot s) {
        Deal d = s.deal();
        Map<String, Object> meta = s.meta();
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("dealId", d.dealId());
        m.put("originApprox", approx(d.originLat(), d.originLng()));
        Double destLat = number(meta.get("destLat"));
        Double destLng = number(meta.get("destLng"));
        m.put("destApprox", destLat == null || destLng == null ? null : approx(destLat, destLng));
        Double distanceKm = number(meta.get("distanceKm"));
        m.put("distanceKm", distanceKm == null ? null : Math.round(distanceKm * 100) / 100.0);
        m.put("basePrice", Math.round(d.basePrice() * 100) / 100.0);
        m.put("lowestBidPrice", d.lowestBidPrice().isPresent() ? d.lowestBidPrice().getAsDouble() : null);
        m.put("riderOfferPrice", d.offer() == null ? null : d.offer().price());
        m.put("bidderCount", d.bids().size());
        m.put("pendingSide", d.pendingSide().name());
        m.put("expiresAt", d.expiresAt().toString());
        m.put("version", d.version());
        return m;
    }

    /** About 100 m: coordinates rounded to 3 decimals for privacy. */
    private static Map<String, Object> approx(double lat, double lng) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("lat", Math.round(lat * 1000) / 1000.0);
        m.put("lng", Math.round(lng * 1000) / 1000.0);
        return m;
    }

    private static Double number(Object v) {
        return v instanceof Number n ? n.doubleValue() : null;
    }
}
