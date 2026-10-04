package com.cdi.dynamicpayroad.engine;

import com.cdi.dynamicpayroad.model.Driver;
import com.cdi.dynamicpayroad.model.Location;
import com.cdi.dynamicpayroad.model.User;
import com.cdi.dynamicpayroad.pool.GeoCellUtil;
import com.cdi.dynamicpayroad.pool.GeoIndexWriter;
import com.cdi.dynamicpayroad.pool.OnlinePool;
import org.springframework.data.geo.Circle;
import org.springframework.data.geo.Distance;
import org.springframework.data.geo.GeoResult;
import org.springframework.data.geo.GeoResults;
import org.springframework.data.geo.Metrics;
import org.springframework.data.geo.Point;
import org.springframework.data.redis.connection.RedisGeoCommands;
import org.springframework.data.redis.core.GeoOperations;
import org.springframework.data.redis.core.RedisOperations;
import org.springframework.data.redis.core.SessionCallback;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * process1: given a requesting user, look only within a 5km radius. The best
 * driver is the nearest waiting one in range; the price multiplier comes from
 * the local demand/supply balance (online users vs. waiting drivers within the
 * same radius). Demand-heavy areas price up (surge), supply-heavy areas price
 * down (discount), with 1.0 = balanced.
 *
 * Demand/supply counts and the nearest driver come from Redis GEO, sharded
 * into cells (GeoCellUtil) instead of one city-wide set — a load test showed
 * that even an indexed GEOSEARCH against a single global set still has to
 * return every match within the radius, and in a dense area that result set
 * itself is the cost. Querying just the origin's cell + its 8 neighbors keeps
 * every count exact (nobody within radius is skipped) while shrinking how
 * much of the population any one query touches.
 *
 * The 9-cell split means 18 GEORADIUS calls (9 cells x users/drivers) per
 * attempt — a second load test caught this as 18 sequential network round
 * trips blocking the calling thread one at a time. They're issued as a single
 * Redis pipeline instead, so the round-trip cost is paid once per attempt,
 * not 18 times.
 */
@Component
public class MatchingEngine {
    private static final double RADIUS_KM = 5.0;

    /**
     * Price multiplier is clamped to this band so fares stay sane at extremes.
     * Floor is below 1.0 so an oversupplied area actually discounts the fare;
     * ceiling caps how far a supply crunch can surge it.
     */
    private static final double MIN_SURGE = 0.7;
    private static final double MAX_SURGE = 3.0;

    private final StringRedisTemplate redis;
    private final OnlinePool pool;

    public MatchingEngine(StringRedisTemplate redis, OnlinePool pool) {
        this.redis = redis;
        this.pool = pool;
    }

    /**
     * Outcome of one match attempt. {@code driver} is null when no waiting
     * driver sits within the radius; the demand/supply/surge fields are still
     * populated so callers can log the local market state either way.
     */
    public record Outcome(Driver driver, double pickupDistanceKm,
                          int demandInRadius, int supplyInRadius, double surge) {
        public boolean matched() { return driver != null; }
    }

    public Outcome evaluate(User user) {
        return evaluateAt(user.getLocation());
    }

    /** Same local demand/supply/surge computation, but around an arbitrary point rather than a requesting user. */
    @SuppressWarnings("unchecked")
    public Outcome evaluateAt(Location origin) {
        Circle within = new Circle(new Point(origin.getLon(), origin.getLat()), new Distance(RADIUS_KM, Metrics.KILOMETERS));
        RedisGeoCommands.GeoRadiusCommandArgs withDistance = RedisGeoCommands.GeoRadiusCommandArgs
                .newGeoRadiusArgs().includeDistance();

        List<String> cells = GeoCellUtil.neighborCellKeys(origin.getLon(), origin.getLat());

        // One pipelined round trip for all 9 cells x (demand, supply) instead of 18 sequential calls.
        List<Object> results = redis.executePipelined(new SessionCallback<Object>() {
            @Override
            public Object execute(RedisOperations operations) {
                GeoOperations<String, String> geoOps = operations.opsForGeo();
                for (String cell : cells) {
                    geoOps.radius(GeoIndexWriter.GEO_USERS_PREFIX + cell, within);
                    geoOps.radius(GeoIndexWriter.GEO_DRIVERS_PREFIX + cell, within, withDistance);
                }
                return null;
            }
        });

        int demand = 0;
        int supply = 0;
        Driver best = null;
        double bestDist = Double.MAX_VALUE;

        for (int i = 0; i < cells.size(); i++) {
            GeoResults<RedisGeoCommands.GeoLocation<String>> demandResults =
                    (GeoResults<RedisGeoCommands.GeoLocation<String>>) results.get(i * 2);
            GeoResults<RedisGeoCommands.GeoLocation<String>> supplyResults =
                    (GeoResults<RedisGeoCommands.GeoLocation<String>>) results.get(i * 2 + 1);

            if (demandResults != null) demand += demandResults.getContent().size();
            if (supplyResults == null) continue;
            supply += supplyResults.getContent().size();
            for (GeoResult<RedisGeoCommands.GeoLocation<String>> r : supplyResults.getContent()) {
                double dist = r.getDistance().getValue();
                if (dist < bestDist) {
                    Driver candidate = pool.peekWaitingDriver(r.getContent().getName());
                    if (candidate != null) {
                        best = candidate;
                        bestDist = dist;
                    }
                }
            }
        }

        double surge = surge(demand, supply);
        return new Outcome(best, best == null ? 0.0 : bestDist, demand, supply, surge);
    }

    /**
     * More riders than nearby drivers pushes price up (>1.0); more drivers than
     * riders pulls it down (<1.0). demand==supply is the neutral 1.0 point.
     * Rounded to 0.1 steps like real surge tiers.
     */
    private double surge(int demand, int supply) {
        if (supply == 0) return MAX_SURGE;
        double ratio = (double) demand / supply;
        double clamped = Math.max(MIN_SURGE, Math.min(MAX_SURGE, ratio));
        return Math.round(clamped * 10.0) / 10.0;
    }
}
