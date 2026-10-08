package com.cdi.dynamicpayroad.redis;

import com.cdi.dynamicpayroad.domain.DealCommand.AcceptOffer;
import com.cdi.dynamicpayroad.domain.DealCommand.PlaceBid;
import com.cdi.dynamicpayroad.domain.DealCommand.PostOffer;
import com.cdi.dynamicpayroad.domain.DealEvent;
import com.cdi.dynamicpayroad.domain.DealStatus;
import com.cdi.dynamicpayroad.domain.Enums.EndReason;
import com.cdi.dynamicpayroad.domain.ErrorCode;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.time.Instant;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Presence on a real Redis (DB 15): sweep.lua step 3, presence_remove.lua and the engaged rule
 * of api-spec §1.5 (R5, R11). Scenarios 13, 17 and 20 of §8.
 * Fixture: basePrice 100 -> band [70, 300]; deal created at T0 (TTL 180 s); presence TTL 60 s.
 */
class LuaPresenceTest extends RedisTestSupport {

    static final Instant T0 = Instant.parse("2026-10-01T00:00:00Z");
    static final Duration TTL = Duration.ofSeconds(60);

    static Instant at(int sec) {
        return T0.plusSeconds(sec);
    }

    void open(String dealId, String riderId) {
        market.createDeal(dealId, riderId, 12.9716, 77.5946, 100.0, Map.of(), T0);
    }

    void register(String driverId) {
        assertThat(market.upsertPresence("DRIVER", driverId, 12.98, 77.60, TTL, T0)).isEqualTo("ONLINE");
    }

    long version(String dealId, int t) {
        return market.snapshot(dealId, at(t)).orElseThrow().deal().version();
    }

    MarketOutcome bid(String dealId, String driverId, double price, int t) {
        return market.apply(dealId, new PlaceBid(driverId, price, 12.98, 77.60, version(dealId, t)), at(t));
    }

    Double score(String member) {
        return cmd.zscore("presence:expiry", member);
    }

    @Test
    @DisplayName("13. 참여 중인 기사의 heartbeat가 60초 넘게 끊김 -> 스윕: 호가 유지, 계속 호가·수락 가능")
    void engagedDriverStaysOnline() {
        open("D-1", "R1");
        register("DR1");
        assertThat(bid("D-1", "DR1", 150, 10).ok()).isTrue();

        MarketOutcome swept = market.sweep(at(70));
        assertThat(swept.ok()).isTrue();
        assertThat(swept.events()).isEmpty();
        assertThat(cmd.exists("presence:driver:DR1")).isEqualTo(1);
        assertThat(cmd.geopos("geo:drivers", "DR1").get(0)).isNotNull();
        assertThat(market.snapshot("D-1", at(70)).orElseThrow().deal().bids()).hasSize(1);

        assertThat(bid("D-1", "DR1", 140, 75).ok()).as("lower bid after the heartbeat lapsed").isTrue();
        market.apply("D-1", new PostOffer("R1", 130, null), at(80));
        MarketOutcome taken = market.apply("D-1", new AcceptOffer("DR1", null), at(85));
        assertThat(taken.ok()).isTrue();
        assertThat(market.snapshot("D-1", at(85)).orElseThrow().deal().status()).isEqualTo(DealStatus.MATCHED);
    }

    @Test
    @DisplayName("17. 참여 중인 승객의 heartbeat가 끊김 -> 스윕: 거래 유지, 180초에 EXPIRED(TTL)로만 끝남")
    void engagedRiderKeepsTheDealUntilTtl() {
        open("D-1", "R1");

        assertThat(market.sweep(at(61)).events()).isEmpty();
        assertThat(cmd.exists("presence:rider:R1")).isEqualTo(1);
        assertThat(market.snapshot("D-1", at(61)).orElseThrow().deal().status()).isEqualTo(DealStatus.OPEN);
        assertThat(market.sweep(at(179)).events()).isEmpty();

        MarketOutcome atTtl = market.sweep(at(180));
        assertThat(atTtl.events().get("D-1")).singleElement()
                .isInstanceOfSatisfying(DealEvent.DealExpired.class, e -> assertThat(e.reason()).isEqualTo(EndReason.TTL));
        // The sweep at 179 pushed the rider to 239 s; then they are no longer engaged and go.
        assertThat(cmd.exists("presence:rider:R1")).isEqualTo(1);
        market.sweep(at(239));
        assertThat(cmd.exists("presence:rider:R1")).isZero();
        assertThat(cmd.geopos("geo:riders", "R1").get(0)).isNull();
    }

    @Test
    @DisplayName("20. 참여 중이 아닌 기사의 heartbeat가 60초 넘게 끊김 -> 스윕 -> 호가: presence 삭제, DRIVER_NOT_AVAILABLE")
    void idleDriverGoesOffline() {
        open("D-1", "R1");
        register("DR1");
        assertThat(market.sweep(at(60)).ok()).isTrue();   // score = 60 000 ≤ now: due, not engaged
        assertThat(cmd.exists("presence:driver:DR1")).isZero();
        assertThat(score("D:DR1")).isNull();
        assertThat(cmd.geopos("geo:drivers", "DR1").get(0)).isNull();

        MarketOutcome r = bid("D-1", "DR1", 150, 61);
        assertThat(r.ok()).isFalse();
        assertThat(r.code()).isEqualTo(ErrorCode.DRIVER_NOT_AVAILABLE);
        assertThat(market.driverStatus("DR1", at(61))).isEqualTo("OFFLINE");
    }

    @Test
    @DisplayName("참여 중인 member는 점수가 nowMs + presenceTtlMs로 밀려 스윕마다 다시 읽히지 않는다")
    void engagedMemberIsPushedBack() {
        open("D-1", "R1");
        register("DR1");
        bid("D-1", "DR1", 150, 10);

        market.sweep(at(70));
        assertThat(score("D:DR1")).isEqualTo((double) at(130).toEpochMilli());
        assertThat(score("R:R1")).isEqualTo((double) at(130).toEpochMilli());
        assertThat(cmd.zrangebyscore("presence:expiry", io.lettuce.core.Range.create(0, at(129).toEpochMilli()))).isEmpty();
        // The stored expiry is not touched: only the sweep index moves.
        assertThat(cmd.hget("presence:driver:DR1", "expiresAt")).isEqualTo(Long.toString(at(60).toEpochMilli()));
    }

    @Test
    @DisplayName("MATCHED 기사도 참여 중: 물리 삭제 전에는 지우지 않는다")
    void matchedDriverIsEngaged() {
        open("D-1", "R1");
        register("DR1");
        market.apply("D-1", new PostOffer("R1", 120, null), at(5));
        assertThat(market.apply("D-1", new AcceptOffer("DR1", null), at(6)).ok()).isTrue();
        assertThat(cmd.scard("driver:DR1:deals")).isZero();

        market.sweep(at(61));
        assertThat(cmd.exists("presence:driver:DR1")).isEqualTo(1);
        assertThat(market.driverStatus("DR1", at(61))).isEqualTo("MATCHED");
        assertThat(market.removePresence("DRIVER", "DR1", at(62))).isFalse();
    }

    @Test
    @DisplayName("presence_remove: 참여 중이면 removed=false, 아니면 삭제하고 removed=true")
    void presenceRemove() {
        open("D-1", "R1");
        register("DR1");
        register("DR2");
        bid("D-1", "DR1", 150, 10);
        assertThat(market.upsertPresence("RIDER", "R9", 12.97, 77.59, TTL, T0)).isEqualTo("ONLINE");

        assertThat(market.removePresence("DRIVER", "DR1", at(20))).isFalse();
        assertThat(market.removePresence("RIDER", "R1", at(20))).isFalse();
        assertThat(cmd.exists("presence:driver:DR1", "presence:rider:R1")).isEqualTo(2);

        assertThat(market.removePresence("DRIVER", "DR2", at(20))).isTrue();
        assertThat(market.removePresence("RIDER", "R9", at(20))).isTrue();
        assertThat(cmd.exists("presence:driver:DR2", "presence:rider:R9")).isZero();
        assertThat(score("D:DR2")).isNull();
        assertThat(score("R:R9")).isNull();
        assertThat(cmd.geopos("geo:drivers", "DR2").get(0)).isNull();
        assertThat(cmd.geopos("geo:riders", "R9").get(0)).isNull();
        assertThat(market.driverStatus("DR2", at(20))).isEqualTo("OFFLINE");
    }

    @Test
    @DisplayName("승객의 거래가 물리 삭제되면 참여 중이 아니다")
    void purgedDealDoesNotKeepTheRider() {
        open("D-1", "R1");
        // A heartbeat at 250 s: due at 310 s, after D-1 is purged at 300 s. activeDealId still names D-1.
        market.upsertPresence("RIDER", "R1", null, null, TTL, at(250));
        market.sweep(at(300));   // closes (TTL) and purges D-1
        assertThat(cmd.exists("deal:D-1")).isZero();
        assertThat(cmd.hget("presence:rider:R1", "activeDealId")).isEqualTo("D-1");
        assertThat(market.removePresence("RIDER", "R1", at(305))).isTrue();
    }

    @Test
    @DisplayName("driverStatus는 읽기만 한다: presence를 연장하지 않는다")
    void driverStatusIsReadOnly() {
        register("DR1");
        assertThat(market.driverStatus("DR1", at(59))).isEqualTo("ONLINE");
        assertThat(market.driverStatus("DR1", at(60))).isEqualTo("OFFLINE");
        assertThat(score("D:DR1")).isEqualTo((double) at(60).toEpochMilli());
        assertThat(market.driverStatus("nobody", T0)).isEqualTo("OFFLINE");
    }
}
