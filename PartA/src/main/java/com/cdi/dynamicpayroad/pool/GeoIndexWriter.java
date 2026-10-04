package com.cdi.dynamicpayroad.pool;

import org.springframework.data.geo.Point;
import org.springframework.data.redis.core.GeoOperations;
import org.springframework.data.redis.core.RedisOperations;
import org.springframework.data.redis.core.SessionCallback;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * Mirrors OnlinePool's add/remove into a grid of per-cell Redis GEO sets
 * (see GeoCellUtil) off whatever thread called OnlinePool — the in-memory
 * ConcurrentHashMaps (the correctness-critical source of truth for
 * claimDriver's double-booking guard) update synchronously and instantly;
 * this index update can lag by a few ms without causing incorrect matches
 * (a stale GEO hit just resolves to a peek() miss and the attempt reports
 * "not matched", which is always a safe outcome).
 *
 * Bulk methods exist because a burst (bootstrap activating tens of thousands
 * of users, or one tick's worth of churn) that fires one GEOADD per entity
 * costs one network round trip each — a load test caught exactly this
 * turning into minutes of queued work. Cells differ per entity, so a single
 * multi-value GEOADD (one key, many members) doesn't fit; a Redis pipeline
 * (many different commands, one round trip) does.
 */
@Component
public class GeoIndexWriter {
    public static final String GEO_USERS_PREFIX = "geo:onlineUsers:cell:";
    public static final String GEO_DRIVERS_PREFIX = "geo:waitingDrivers:cell:";

    public record GeoAdd(String id, double lon, double lat) {}

    private final StringRedisTemplate redis;

    public GeoIndexWriter(StringRedisTemplate redis) {
        this.redis = redis;
    }

    /** Singular add for scattered, one-at-a-time events (e.g. a single driver
     *  returning to the pool after a trip) — not worth batching since these
     *  don't naturally co-occur in a tight loop. */
    @Async("geoIndexExecutor")
    public void addUser(String userId, double lon, double lat) {
        redis.opsForGeo().add(GEO_USERS_PREFIX + GeoCellUtil.cellKeyFor(lon, lat), new Point(lon, lat), userId);
    }

    @Async("geoIndexExecutor")
    public void addDriver(String driverId, double lon, double lat) {
        redis.opsForGeo().add(GEO_DRIVERS_PREFIX + GeoCellUtil.cellKeyFor(lon, lat), new Point(lon, lat), driverId);
    }

    /** Bulk add for bursts (bootstrap activation, one tick's worth of churn) —
     *  one pipelined round trip instead of one per entity. */
    @Async("geoIndexExecutor")
    public void addUsersBulk(List<GeoAdd> adds) {
        addBulk(GEO_USERS_PREFIX, adds);
    }

    @Async("geoIndexExecutor")
    public void addDriversBulk(List<GeoAdd> adds) {
        addBulk(GEO_DRIVERS_PREFIX, adds);
    }

    private void addBulk(String prefix, List<GeoAdd> adds) {
        if (adds.isEmpty()) return;
        redis.executePipelined(new SessionCallback<Object>() {
            @Override
            @SuppressWarnings("unchecked")
            public Object execute(RedisOperations operations) {
                GeoOperations<String, String> geoOps = operations.opsForGeo();
                for (GeoAdd a : adds) {
                    String key = prefix + GeoCellUtil.cellKeyFor(a.lon(), a.lat());
                    geoOps.add(key, new Point(a.lon(), a.lat()), a.id());
                }
                return null;
            }
        });
    }

    @Async("geoIndexExecutor")
    public void removeUser(String userId, double lon, double lat) {
        redis.opsForZSet().remove(GEO_USERS_PREFIX + GeoCellUtil.cellKeyFor(lon, lat), userId);
    }

    @Async("geoIndexExecutor")
    public void removeDriver(String driverId, double lon, double lat) {
        redis.opsForZSet().remove(GEO_DRIVERS_PREFIX + GeoCellUtil.cellKeyFor(lon, lat), driverId);
    }
}
