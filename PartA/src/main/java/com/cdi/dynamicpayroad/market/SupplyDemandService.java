package com.cdi.dynamicpayroad.market;

import com.cdi.dynamicpayroad.redis.RedisMarket;
import org.springframework.stereotype.Service;

/**
 * Local demand, supply and surge (api-spec §4.8) from Redis GEO: online riders (geo:riders) and
 * ONLINE, not MATCHED drivers (geo:drivers) within 5 km.
 */
@Service
public class SupplyDemandService {

    public static final double RADIUS_KM = 5.0;
    private static final double MIN_SURGE = 0.7;
    private static final double MAX_SURGE = 3.0;

    public record Snapshot(int demand, int supply, double surge) {}

    private final RedisMarket redisMarket;

    public SupplyDemandService(RedisMarket redisMarket) {
        this.redisMarket = redisMarket;
    }

    public Snapshot at(double lat, double lng) {
        int demand = redisMarket.countNearby("geo:riders", lat, lng, RADIUS_KM);
        int supply = redisMarket.countNearby("geo:drivers", lat, lng, RADIUS_KM);
        return new Snapshot(demand, supply, surge(demand, supply));
    }

    /** clamp(demand / max(supply, 1), 0.7, 3.0), rounded to 0.1 (the old MatchingEngine formula). */
    public static double surge(int demand, int supply) {
        double ratio = (double) demand / Math.max(supply, 1);
        double clamped = Math.max(MIN_SURGE, Math.min(MAX_SURGE, ratio));
        return Math.round(clamped * 10.0) / 10.0;
    }
}
