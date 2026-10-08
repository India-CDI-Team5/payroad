package com.cdi.dynamicpayroad.presence;

import com.cdi.dynamicpayroad.redis.RedisMarket;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Optional;

/**
 * Who is online (api-spec §4.5-4.7, R5, R11). Registration and heartbeat are presence_upsert.lua;
 * expiry is sweep.lua step 3, which never logs off an engaged user (§1.5). Nothing here withdraws
 * bids or cancels deals because someone went quiet.
 */
@Service
public class PresenceService {

    private final Clock clock;
    private final RedisMarket redisMarket;
    private final Duration ttl;

    public PresenceService(Clock clock, RedisMarket redisMarket, @Value("${presence.ttl-sec:60}") long ttlSec) {
        this.clock = clock;
        this.redisMarket = redisMarket;
        this.ttl = Duration.ofSeconds(ttlSec);
    }

    /** §4.5. Returns the new expiry (now + TTL). */
    public Instant registerDriver(String driverId, double lat, double lng) {
        return upsert("DRIVER", driverId, lat, lng)
                .orElseThrow(() -> new IllegalStateException("driver registration refused: " + driverId));
    }

    /** §4.6. Coordinates are optional for riders. */
    public Instant registerRider(String riderId, Double lat, Double lng) {
        return upsert("RIDER", riderId, lat, lng)
                .orElseThrow(() -> new IllegalStateException("rider registration refused: " + riderId));
    }

    /** §4.7. Empty when a driver who never registered sends no position. */
    public Optional<Instant> heartbeat(String actorId, String actorType, Double lat, Double lng) {
        return upsert(actorType, actorId, lat, lng);
    }

    /** ONLINE, MATCHED or OFFLINE. Read-only: does not extend the presence. */
    public String driverStatus(String driverId) {
        return redisMarket.driverStatus(driverId, clock.instant());
    }

    private Optional<Instant> upsert(String actorType, String actorId, Double lat, Double lng) {
        Instant now = clock.instant();
        String status = redisMarket.upsertPresence(actorType, actorId, lat, lng, ttl, now);
        // Redis keeps epoch ms; report the same instant it stored.
        return status == null ? Optional.empty() : Optional.of(Instant.ofEpochMilli(now.toEpochMilli() + ttl.toMillis()));
    }
}
