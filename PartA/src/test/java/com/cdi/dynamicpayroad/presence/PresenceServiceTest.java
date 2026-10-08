package com.cdi.dynamicpayroad.presence;

import com.cdi.dynamicpayroad.domain.DealCommand.PlaceBid;
import com.cdi.dynamicpayroad.domain.ErrorCode;
import com.cdi.dynamicpayroad.redis.MarketOutcome;
import com.cdi.dynamicpayroad.redis.RedisTestSupport;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/** PresenceService on a real Redis (DB 15) with a clock the test moves. Presence TTL 60 s, deal TTL 180 s. */
class PresenceServiceTest extends RedisTestSupport {

    static final Instant T0 = Instant.parse("2026-10-01T00:00:00Z");

    static final class MovableClock extends Clock {
        private Instant now = T0;
        void set(int secondsAfterT0) { now = T0.plusSeconds(secondsAfterT0); }
        @Override public Instant instant() { return now; }
        @Override public ZoneId getZone() { return ZoneOffset.UTC; }
        @Override public Clock withZone(ZoneId zone) { return this; }
    }

    MovableClock clock;
    PresenceService presence;

    @BeforeEach
    void setUp() {
        clock = new MovableClock();
        presence = new PresenceService(clock, market, 60);
        market.createDeal("D-1", "R1", 12.9716, 77.5946, 100.0, Map.of(), T0);
    }

    MarketOutcome bid(String driverId, double price) {
        return market.apply("D-1", new PlaceBid(driverId, price, 12.98, 77.60, null), clock.instant());
    }

    @Test
    void registeredDriverCanBidUntilTheTtl() {
        assertThat(presence.registerDriver("DR1", 12.98, 77.60)).isEqualTo(T0.plusSeconds(60));
        assertThat(presence.driverStatus("DR1")).isEqualTo("ONLINE");

        clock.set(59);
        assertThat(bid("DR1", 150).ok()).isTrue();
    }

    @Test
    void idleDriverIsOfflineAfterTheSweep() {
        presence.registerDriver("DR1", 12.98, 77.60);

        clock.set(61);
        market.sweep(clock.instant());
        assertThat(presence.driverStatus("DR1")).isEqualTo("OFFLINE");
        MarketOutcome r = bid("DR1", 150);
        assertThat(r.ok()).isFalse();
        assertThat(r.code()).isEqualTo(ErrorCode.DRIVER_NOT_AVAILABLE);
    }

    @Test
    void heartbeatExtendsTheExpiry() {
        presence.registerDriver("DR1", 12.98, 77.60);

        clock.set(50);
        assertThat(presence.heartbeat("DR1", "DRIVER", null, null)).contains(T0.plusSeconds(110));

        clock.set(61);
        market.sweep(clock.instant());
        assertThat(presence.driverStatus("DR1")).isEqualTo("ONLINE");
        clock.set(100);
        assertThat(bid("DR1", 150).ok()).isTrue();
    }

    @Test
    void unregisteredDriverWithoutPositionIsRefused() {
        assertThat(presence.heartbeat("DR9", "DRIVER", null, null)).isEmpty();
        assertThat(presence.heartbeat("DR9", "DRIVER", 12.98, 77.60)).contains(T0.plusSeconds(60));
        assertThat(presence.heartbeat("R9", "RIDER", null, null)).contains(T0.plusSeconds(60));
    }

    @Test
    void driverStatusDoesNotExtendThePresence() {
        presence.registerDriver("DR1", 12.98, 77.60);
        clock.set(30);
        presence.driverStatus("DR1");
        clock.set(60);
        assertThat(presence.driverStatus("DR1")).isEqualTo("OFFLINE");
        assertThat(Duration.ofMillis(Long.parseLong(cmd.hget("presence:driver:DR1", "expiresAt")) - T0.toEpochMilli()))
                .isEqualTo(Duration.ofSeconds(60));
    }
}
