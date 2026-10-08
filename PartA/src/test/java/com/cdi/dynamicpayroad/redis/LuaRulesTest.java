package com.cdi.dynamicpayroad.redis;

import com.cdi.dynamicpayroad.domain.Deal;
import com.cdi.dynamicpayroad.domain.DealCommand;
import com.cdi.dynamicpayroad.domain.DealCommand.AcceptBid;
import com.cdi.dynamicpayroad.domain.DealCommand.AcceptOffer;
import com.cdi.dynamicpayroad.domain.DealCommand.Cancel;
import com.cdi.dynamicpayroad.domain.DealCommand.PlaceBid;
import com.cdi.dynamicpayroad.domain.DealCommand.PostOffer;
import com.cdi.dynamicpayroad.domain.DealCommand.WithdrawBid;
import com.cdi.dynamicpayroad.domain.DealEvent;
import com.cdi.dynamicpayroad.domain.DealEvent.BidPlaced;
import com.cdi.dynamicpayroad.domain.DealEvent.BidUpdated;
import com.cdi.dynamicpayroad.domain.DealEvent.BidWithdrawn;
import com.cdi.dynamicpayroad.domain.DealEvent.DealExpired;
import com.cdi.dynamicpayroad.domain.DealEvent.DealMatched;
import com.cdi.dynamicpayroad.domain.DealEvent.OfferExpired;
import com.cdi.dynamicpayroad.domain.DealEvent.OfferPosted;
import com.cdi.dynamicpayroad.domain.DealRules;
import com.cdi.dynamicpayroad.domain.DealStatus;
import com.cdi.dynamicpayroad.domain.Enums.EndReason;
import com.cdi.dynamicpayroad.domain.Enums.MatchPath;
import com.cdi.dynamicpayroad.domain.Enums.PendingSide;
import com.cdi.dynamicpayroad.domain.Enums.WithdrawReason;
import com.cdi.dynamicpayroad.domain.ErrorCode;
import com.cdi.dynamicpayroad.domain.Geo;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

/**
 * The bargaining rules as implemented by the Lua scripts, on a real Redis (DB 15).
 *
 * <p>(a) Every assertion of the former DealStateMachineTest / MarketStateMachineTest, same inputs
 * and expectations (Tick → sweep at the same time). Where the Java tests applied several
 * commands to one immutable state, each branch rebuilds that state (new dealId or FLUSHDB).
 * Rejection messages contain numbers formatted differently in Java and Lua, so only code and
 * version are asserted.
 * (b) api-spec §8 scenarios 1-12, 14, 15, 16, 18, 19 (13, 17, 20 belong to card A3).
 * (c)-(j) R13, closing cleanup, determinism, purge, untouched state on rejection, empty actor
 * ids, empty event lists, and the round-limit reply shape.
 *
 * Fixture: basePrice 100 -> band [70, 300]; deals created at T0, TTL 180 s, offer TTL 30 s.
 */
class LuaRulesTest extends RedisTestSupport {

    static final Instant T0 = Instant.parse("2026-10-01T00:00:00Z");
    static final DealRules RULES = DealRules.defaults();
    /** Long enough that presence never lapses inside a test (DriverAvailability.ALL of the old tests). */
    static final Duration ALWAYS = Duration.ofHours(1);

    // --- helpers -------------------------------------------------------------------------------

    static Instant at(int secondsAfterT0) {
        return T0.plusSeconds(secondsAfterT0);
    }

    void open(String dealId, String riderId, double lat, double lng, double basePrice, int t) {
        market.createDeal(dealId, riderId, lat, lng, basePrice, Map.of(), at(t));
    }

    /** Deal.open("D-…", "R1", 12.9716, 77.5946, 100.0, T0) of the old tests. */
    void open(String dealId) {
        open(dealId, "R1", 12.9716, 77.5946, 100.0, 0);
    }

    void online(String... drivers) {
        for (String d : drivers) {
            assertThat(market.upsertPresence("DRIVER", d, 12.98, 77.60, ALWAYS, T0)).isEqualTo("ONLINE");
        }
    }

    MarketOutcome apply(String dealId, DealCommand command, int t) {
        return market.apply(dealId, command, at(t));
    }

    Deal deal(String dealId) {
        return market.snapshot(dealId, T0).orElseThrow().deal();
    }

    static MarketOutcome ok(MarketOutcome r) {
        assertThat(r.ok()).as("expected the command to be accepted, got %s %s", r.code(), r.message()).isTrue();
        return r;
    }

    static MarketOutcome rejected(MarketOutcome r, ErrorCode code) {
        assertThat(r.ok()).as("expected a rejection with %s", code).isFalse();
        assertThat(r.code()).isEqualTo(code);
        return r;
    }

    static List<DealEvent> events(MarketOutcome r, String dealId) {
        return r.events().getOrDefault(dealId, List.of());
    }

    static DealEvent first(MarketOutcome r, String dealId) {
        return events(r, dealId).get(0);
    }

    /** A bid placed 1 km-ish from the origin, with the deal's current version. */
    Deal bid(String dealId, String driver, double price, int t) {
        ok(apply(dealId, new PlaceBid(driver, price, 12.98, 77.60, deal(dealId).version()), t));
        return deal(dealId);
    }

    Deal offer(String dealId, double price, int t) {
        ok(apply(dealId, new PostOffer(deal(dealId).riderId(), price, deal(dealId).version()), t));
        return deal(dealId);
    }

    static Deal.Bid bidOf(Deal d, String driver) {
        return d.bids().stream().filter(b -> b.driverId().equals(driver)).findFirst().orElseThrow();
    }

    boolean activeBidIndexed(String driver, String dealId) {
        return cmd.sismember("driver:" + driver + ":deals", dealId);
    }

    // =============================================================================================
    // (a) former DealStateMachineTest / MarketStateMachineTest
    // =============================================================================================

    @Nested
    class FormerJavaTests {

        @Test
        @DisplayName("1. 정상 협상: 호가 2건 -> 승객이 비싼 호가를 지목 -> MATCHED, chosenRank = 2")
        void riderPicksBid() {
            open("D-1");
            online("DR1", "DR2");
            Deal d = bid("D-1", "DR1", 150, 5);
            assertThat(d.status()).isEqualTo(DealStatus.NEGOTIATING);
            assertThat(d.pendingSide()).isEqualTo(PendingSide.RIDER);
            d = bid("D-1", "DR2", 130, 6);
            assertThat(d.round()).isEqualTo(2);
            assertThat(d.version()).isEqualTo(3);
            String pricier = bidOf(d, "DR1").bidId();

            MarketOutcome r = ok(apply("D-1", new AcceptBid("R1", pricier, d.version()), 10));
            assertThat(deal("D-1").status()).isEqualTo(DealStatus.MATCHED);
            DealMatched m = (DealMatched) first(r, "D-1");
            assertThat(m.match().driverId()).isEqualTo("DR1");
            assertThat(m.match().finalPrice()).isEqualTo(150);
            assertThat(m.match().matchPath()).isEqualTo(MatchPath.RIDER_PICKED_BID);
            assertThat(m.match().chosenRank()).isEqualTo(2);
            assertThat(m.match().lowestBidPrice()).isEqualTo(130);
            assertThat(m.version()).isEqualTo(4);
        }

        @Test
        @DisplayName("2. 기사 선착 수락: 승객 오퍼 -> 기사 수락 -> 오퍼 가격으로 MATCHED. 오퍼가 없으면 OFFER_NOT_FOUND")
        void driverTakesOffer() {
            open("D-1");
            online("DR1");
            rejected(apply("D-1", new AcceptOffer("DR1", 1L), 1), ErrorCode.OFFER_NOT_FOUND);

            MarketOutcome posted = ok(apply("D-1", new PostOffer("R1", 120, 1L), 2));
            assertThat(first(posted, "D-1")).isInstanceOf(OfferPosted.class);
            assertThat(deal("D-1").pendingSide()).isEqualTo(PendingSide.DRIVER);

            Deal d = deal("D-1");
            MarketOutcome r = ok(apply("D-1", new AcceptOffer("DR1", d.version()), 10));
            DealMatched m = (DealMatched) first(r, "D-1");
            assertThat(m.match().finalPrice()).isEqualTo(120);
            assertThat(m.match().matchPath()).isEqualTo(MatchPath.DRIVER_TOOK_OFFER);
            assertThat(deal("D-1").status()).isEqualTo(DealStatus.MATCHED);
        }

        @Test
        @DisplayName("3. R1 기사 단조성: 자기 직전 호가보다 올릴 수 없고, 철회 후 재입찰해도 기준이 유지된다")
        void driverMonotonic() {
            open("D-1");
            online("DR1", "DR2");
            Deal d = bid("D-1", "DR1", 150, 1);
            rejected(apply("D-1", new PlaceBid("DR1", 160, 12.98, 77.60, d.version()), 2), ErrorCode.PRICE_NOT_CONCEDED);

            MarketOutcome lower = ok(apply("D-1", new PlaceBid("DR1", 140, 12.98, 77.60, d.version()), 3));
            assertThat(first(lower, "D-1")).isInstanceOf(BidUpdated.class);

            // Another driver may bid above the current lowest: R1 compares a driver only with himself.
            d = bid("D-1", "DR2", 200, 4);

            ok(apply("D-1", new WithdrawBid("DR1", d.version()), 5));
            d = deal("D-1");
            rejected(apply("D-1", new PlaceBid("DR1", 145, 12.98, 77.60, d.version()), 6), ErrorCode.PRICE_NOT_CONCEDED);
            ok(apply("D-1", new PlaceBid("DR1", 140, 12.98, 77.60, d.version()), 7));   // equal is allowed
        }

        @Test
        @DisplayName("4. R1 승객 단조성 + 소유권: 오퍼는 낮출 수 없고, 남의 거래에는 낼 수 없다")
        void riderMonotonicAndOwner() {
            open("D-1");
            ok(apply("D-1", new PostOffer("R1", 110, 1L), 1));
            Deal d = deal("D-1");
            rejected(apply("D-1", new PostOffer("R1", 100, d.version()), 2), ErrorCode.PRICE_NOT_CONCEDED);
            ok(apply("D-1", new PostOffer("R1", 115, d.version()), 3));

            // The Java test sent R2's offer to the state before the 115 offer: rebuild it.
            open("D-1b");
            ok(apply("D-1b", new PostOffer("R1", 110, 1L), 1));
            Deal b = deal("D-1b");
            rejected(apply("D-1b", new PostOffer("R2", 115, b.version()), 4), ErrorCode.NOT_DEAL_OWNER);
        }

        @Test
        @DisplayName("5. R2 호가 밴드: basePrice x [0.7, 3.0] 밖은 OUT_OF_BAND, 경계값은 허용")
        void band() {
            open("D-1");
            online("DR1", "DR2");
            rejected(apply("D-1", new PlaceBid("DR1", 69.99, 12.98, 77.60, 1L), 1), ErrorCode.OUT_OF_BAND);
            rejected(apply("D-1", new PlaceBid("DR1", 300.01, 12.98, 77.60, 1L), 1), ErrorCode.OUT_OF_BAND);
            rejected(apply("D-1", new PostOffer("R1", 60, 1L), 1), ErrorCode.OUT_OF_BAND);
            bid("D-1", "DR1", 70, 2);
            bid("D-1", "DR2", 300, 3);
        }

        @Test
        @DisplayName("6. R5 호가 대체·철회: 기사당 1건, 철회는 라운드에 안 들어가고, 철회된 호가는 지목할 수 없다")
        void replaceAndWithdraw() {
            open("D-1");
            online("DR1");
            Deal d = bid("D-1", "DR1", 150, 1);
            String oldBidId = d.bids().get(0).bidId();
            d = bid("D-1", "DR1", 140, 2);
            assertThat(d.bids()).hasSize(1);
            int roundBefore = d.round();

            MarketOutcome w = ok(apply("D-1", new WithdrawBid("DR1", d.version()), 3));
            BidWithdrawn e = (BidWithdrawn) first(w, "D-1");
            assertThat(e.reason()).isEqualTo(WithdrawReason.BY_DRIVER);
            Deal after = deal("D-1");
            assertThat(after.round()).isEqualTo(roundBefore);
            assertThat(after.withdrawCount()).isEqualTo(1);
            assertThat(after.bids()).isEmpty();

            rejected(apply("D-1", new AcceptBid("R1", oldBidId, after.version()), 4), ErrorCode.BID_NOT_FOUND);
        }

        @Test
        @DisplayName("7. R6 오퍼 TTL 30초: 지나면 수락은 OFFER_EXPIRED, 스윕은 offer.expired를 내고 pendingSide = RIDER")
        void offerTtl() {
            open("D-1");
            online("DR1");
            ok(apply("D-1", new PostOffer("R1", 120, 1L), 0));
            Deal d = deal("D-1");
            rejected(apply("D-1", new AcceptOffer("DR1", d.version()), 31), ErrorCode.OFFER_EXPIRED);

            MarketOutcome t = ok(market.sweep(at(31)));
            assertThat(t.events()).containsOnlyKeys("D-1");
            assertThat(events(t, "D-1")).singleElement().isInstanceOf(OfferExpired.class);
            assertThat(deal("D-1").offer()).isNull();
            assertThat(deal("D-1").pendingSide()).isEqualTo(PendingSide.RIDER);
        }

        @Test
        @DisplayName("8. R7 거래 TTL 180초: 179초엔 변화 없음, 180초에 EXPIRED(TTL), 이후 행위는 DEAL_NOT_ACTIVE")
        void dealTtl() {
            open("D-1");
            online("DR1", "DR2");
            Deal d = bid("D-1", "DR1", 150, 1);
            MarketOutcome before = ok(market.sweep(at(179)));
            assertThat(before.events()).isEmpty();
            assertThat(deal("D-1").version()).isEqualTo(d.version());

            MarketOutcome atTtl = ok(market.sweep(at(180)));
            assertThat(deal("D-1").status()).isEqualTo(DealStatus.EXPIRED);
            assertThat(((DealExpired) first(atTtl, "D-1")).reason()).isEqualTo(EndReason.TTL);

            rejected(apply("D-1", new PlaceBid("DR2", 120, 12.98, 77.60, deal("D-1").version()), 181), ErrorCode.DEAL_NOT_ACTIVE);

            // A deal with no bids at all expires the same way (fresh() reused in the Java test).
            open("D-1b");
            ok(market.sweep(at(180)));
            assertThat(deal("D-1b").status()).isEqualTo(DealStatus.EXPIRED);
        }

        @Test
        @DisplayName("9. R8 라운드 상한 20: 21번째 행위는 반영되지 않고 거래가 EXPIRED(ROUND_LIMIT)")
        void roundLimit() {
            open("D-1");
            online("DR1", "DR2");
            Deal d = deal("D-1");
            for (int i = 0; i < 20; i++) {
                d = bid("D-1", i % 2 == 0 ? "DR1" : "DR2", 250 - i, i + 1);   // each driver keeps conceding
            }
            assertThat(d.round()).isEqualTo(20);

            MarketOutcome r = ok(apply("D-1", new PlaceBid("DR1", 200, 12.98, 77.60, d.version()), 30));
            Deal after = deal("D-1");
            assertThat(after.status()).isEqualTo(DealStatus.EXPIRED);
            assertThat(events(r, "D-1")).singleElement().isInstanceOf(DealExpired.class);
            assertThat(((DealExpired) first(r, "D-1")).reason()).isEqualTo(EndReason.ROUND_LIMIT);
            assertThat(after.round()).isEqualTo(20);
        }

        @Test
        @DisplayName("10. R9 단일 체결 + version CAS: 같은 version의 두 수락 중 두 번째는 DEAL_ALREADY_MATCHED, 낡은 version은 VERSION_CONFLICT")
        void singleMatchAndVersion() {
            long seen = singleMatchSetup();
            String bidId = deal("D-1").bids().get(0).bidId();
            ok(apply("D-1", new AcceptBid("R1", bidId, seen), 3));
            rejected(apply("D-1", new AcceptOffer("DR2", seen), 3), ErrorCode.DEAL_ALREADY_MATCHED);

            // The Java test sent the stale bid to the state before the match: rebuild it from scratch
            // (DR1 is MATCHED now, so the same setup needs an empty DB).
            market.flushDb();
            long seenAgain = singleMatchSetup();
            rejected(apply("D-1", new PlaceBid("DR2", 130, 12.98, 77.60, seenAgain - 1), 4), ErrorCode.VERSION_CONFLICT);
        }

        long singleMatchSetup() {
            open("D-1");
            online("DR1", "DR2");
            Deal d = bid("D-1", "DR1", 150, 1);
            ok(apply("D-1", new PostOffer("R1", 120, d.version()), 2));
            return deal("D-1").version();
        }

        @Test
        @DisplayName("12. R12 승객 취소: 본인만 취소 가능, CANCELLED(CANCELLED_BY_RIDER) 후 호가 전부 철회, 이후 수락은 DEAL_NOT_ACTIVE")
        void cancel() {
            open("D-1");
            online("DR1");
            Deal d = bid("D-1", "DR1", 150, 1);
            rejected(apply("D-1", new Cancel("R2"), 2), ErrorCode.NOT_DEAL_OWNER);

            MarketOutcome c = ok(apply("D-1", new Cancel("R1"), 3));
            Deal after = deal("D-1");
            assertThat(after.status()).isEqualTo(DealStatus.CANCELLED);
            assertThat(after.bids()).isEmpty();
            assertThat(events(c, "D-1")).anySatisfy(e -> {
                assertThat(e).isInstanceOf(DealExpired.class);
                assertThat(((DealExpired) e).reason()).isEqualTo(EndReason.CANCELLED_BY_RIDER);
            });

            String bidId = d.bids().get(0).bidId();
            rejected(apply("D-1", new AcceptBid("R1", bidId, after.version()), 4), ErrorCode.DEAL_NOT_ACTIVE);
        }

        @Test
        @DisplayName("(보조) R11 기사 자격·version: 자격 없는 기사는 DRIVER_NOT_AVAILABLE, 낡은 version은 VERSION_CONFLICT, 없는 호가 철회는 BID_NOT_FOUND")
        void driverEligibilityAndVersion() {
            open("D-1");
            online("DR1");   // only DR1 is available at first
            MarketOutcome offline = apply("D-1", new PlaceBid("DR2", 150, 12.98, 77.60, 1L), 0);
            rejected(offline, ErrorCode.DRIVER_NOT_AVAILABLE);

            Deal d = bid("D-1", "DR1", 150, 1);
            rejected(apply("D-1", new PlaceBid("DR1", 140, 12.98, 77.60, d.version() - 1), 2), ErrorCode.VERSION_CONFLICT);
            online("DR2");   // the Java test used DriverAvailability.ALL from here on
            rejected(apply("D-1", new WithdrawBid("DR2", d.version()), 3), ErrorCode.BID_NOT_FOUND);

            // Rejections leave the deal untouched and report its current version.
            assertThat(offline.version()).isEqualTo(1);
        }

        @Test
        @DisplayName("(보조) TTL이 지나면 스윕 전이라도 행동은 DEAL_NOT_ACTIVE, 오퍼 수락은 chosenRank 0과 수락 기사 자신의 픽업 거리를 기록")
        void ttlGapAndOfferMatchFields() {
            Deal d = offerMatchSetup(true);
            DealMatched byBidder = (DealMatched) first(ok(apply("D-1", new AcceptOffer("DR1", d.version()), 4)), "D-1");
            assertThat(byBidder.match().chosenRank()).isZero();
            assertThat(byBidder.match().finalPrice()).isEqualTo(125);
            assertThat(byBidder.match().lowestBidPrice()).isEqualTo(130);
            assertThat(byBidder.match().pickupDistanceKm()).isNotNull();

            // Second branch from the same state: rebuild it (DR1 is MATCHED now).
            market.flushDb();
            d = offerMatchSetup(false);
            DealMatched byStranger = (DealMatched) first(ok(apply("D-1", new AcceptOffer("DR9", d.version()), 4)), "D-1");
            assertThat(byStranger.match().pickupDistanceKm()).isNull();
        }

        Deal offerMatchSetup(boolean checkTtlGap) {
            open("D-1");
            online("DR1", "DR2", "DR9");
            Deal d = bid("D-1", "DR1", 150, 1);
            if (checkTtlGap) {
                rejected(apply("D-1", new PlaceBid("DR2", 120, 12.98, 77.60, d.version()), 180), ErrorCode.DEAL_NOT_ACTIVE);
            }
            bid("D-1", "DR2", 130, 2);
            return offer("D-1", 125, 3);
        }

        @Test
        @DisplayName("(보조) 첫 호가는 bid.placed, 서버가 픽업 거리·ETA를 계산한다 (Java Geo.haversineKm과 1e-9 안)")
        void firstBidEvent() {
            open("D-1");
            online("DR1");
            MarketOutcome r = ok(apply("D-1", new PlaceBid("DR1", 150, 12.98, 77.60, 1L), 1));
            BidPlaced e = (BidPlaced) first(r, "D-1");
            assertThat(e.bid().pickupDistanceKm()).isGreaterThan(0);
            assertThat(e.bid().pickupDistanceKm()).isCloseTo(Geo.haversineKm(12.98, 77.60, 12.9716, 77.5946), within(1e-9));
            assertThat(e.bid().pickupEtaMin()).isEqualTo(RULES.pickupEtaMin(e.bid().pickupDistanceKm()));
            assertThat(e.bidderCount()).isEqualTo(1);
        }

        @Test
        @DisplayName("11. R10·R11 이중 체결 차단: 체결된 기사의 다른 호가는 즉시 철회되고, 이후 그 기사와 오프라인 기사는 DRIVER_NOT_AVAILABLE")
        void doubleMatchBlocked() {
            open("D-1", "R1", 12.97, 77.59, 100, 0);
            open("D-2", "R2", 12.93, 77.62, 100, 0);
            open("D-3", "R3", 12.95, 77.60, 100, 0);
            online("DR1", "DR2");
            bid("D-1", "DR1", 150, 1);
            bid("D-2", "DR1", 140, 1);
            bid("D-2", "DR2", 160, 1);

            Deal d1 = deal("D-1");
            MarketOutcome r = ok(apply("D-1", new AcceptBid("R1", d1.bids().get(0).bidId(), d1.version()), 5));

            assertThat(events(r, "D-1")).anySatisfy(e -> assertThat(e).isInstanceOf(DealMatched.class));
            assertThat(events(r, "D-2")).singleElement().satisfies(e -> {
                assertThat(e).isInstanceOf(BidWithdrawn.class);
                assertThat(((BidWithdrawn) e).driverId()).isEqualTo("DR1");
                assertThat(((BidWithdrawn) e).reason()).isEqualTo(WithdrawReason.DRIVER_MATCHED_ELSEWHERE);
            });
            assertThat(deal("D-2").bids()).extracting(Deal.Bid::driverId).containsExactly("DR2");
            assertThat(cmd.hget("driver:DR1:state", "status")).isEqualTo("MATCHED");

            long v3 = deal("D-3").version();
            rejected(apply("D-3", new PlaceBid("DR1", 130, 12.98, 77.60, v3), 6), ErrorCode.DRIVER_NOT_AVAILABLE);
            rejected(apply("D-3", new PlaceBid("DR9", 130, 12.98, 77.60, v3), 6), ErrorCode.DRIVER_NOT_AVAILABLE);
        }
    }

    // =============================================================================================
    // (b) api-spec §8 scenarios
    // =============================================================================================

    @Nested
    class SpecScenarios {

        @Test
        @DisplayName("§8-1 정상 협상 → 승객이 최저가 수락: MATCHED, chosenRank=1")
        void s01_lowestAccepted() {
            open("D-1");
            online("DR1", "DR2");
            bid("D-1", "DR1", 150, 1);
            Deal d = bid("D-1", "DR2", 130, 2);
            MarketOutcome r = ok(apply("D-1", new AcceptBid("R1", bidOf(d, "DR2").bidId(), d.version()), 3));
            assertThat(deal("D-1").status()).isEqualTo(DealStatus.MATCHED);
            assertThat(((DealMatched) first(r, "D-1")).match().chosenRank()).isEqualTo(1);
        }

        @Test
        @DisplayName("§8-2 승객이 2번째로 싼 호가 수락: MATCHED, chosenRank=2")
        void s02_secondCheapestAccepted() {
            open("D-1");
            online("DR1", "DR2");
            bid("D-1", "DR1", 150, 1);
            Deal d = bid("D-1", "DR2", 130, 2);
            MarketOutcome r = ok(apply("D-1", new AcceptBid("R1", bidOf(d, "DR1").bidId(), d.version()), 3));
            assertThat(deal("D-1").status()).isEqualTo(DealStatus.MATCHED);
            DealMatched m = (DealMatched) first(r, "D-1");
            assertThat(m.match().chosenRank()).isEqualTo(2);
            assertThat(m.match().lowestBidPrice()).isEqualTo(130);
        }

        @Test
        @DisplayName("§8-3 기사가 자기 호가를 올림: PRICE_NOT_CONCEDED")
        void s03_driverRaises() {
            open("D-1");
            online("DR1");
            Deal d = bid("D-1", "DR1", 150, 1);
            rejected(apply("D-1", new PlaceBid("DR1", 150.5, 12.98, 77.60, d.version()), 2), ErrorCode.PRICE_NOT_CONCEDED);
        }

        @Test
        @DisplayName("§8-4 기사가 자기 호가를 내림: 정상 접수, 이전 호가 대체(bid.updated, 새 bidId)")
        void s04_driverLowers() {
            open("D-1");
            online("DR1");
            Deal d = bid("D-1", "DR1", 150, 1);
            String oldId = d.bids().get(0).bidId();
            MarketOutcome r = ok(apply("D-1", new PlaceBid("DR1", 140, 12.98, 77.60, d.version()), 2));
            BidUpdated e = (BidUpdated) first(r, "D-1");
            assertThat(e.bid().bidId()).isNotEqualTo(oldId);
            assertThat(deal("D-1").bids()).singleElement().satisfies(b -> {
                assertThat(b.bidId()).isEqualTo(e.bid().bidId());
                assertThat(b.price()).isEqualTo(140);
            });
        }

        @Test
        @DisplayName("§8-5 기사 B가 기사 A보다 비싸게 호가: 정상 접수(전역 개선 불필요)")
        void s05_higherThanOthersAccepted() {
            open("D-1");
            online("DR1", "DR2");
            Deal d = bid("D-1", "DR1", 130, 1);
            MarketOutcome r = ok(apply("D-1", new PlaceBid("DR2", 150, 12.98, 77.60, d.version()), 2));
            BidPlaced e = (BidPlaced) first(r, "D-1");
            assertThat(e.lowestBidPrice()).isEqualTo(130);
            assertThat(e.bidderCount()).isEqualTo(2);
        }

        @Test
        @DisplayName("§8-6 승객이 오퍼를 내림: PRICE_NOT_CONCEDED")
        void s06_riderLowers() {
            open("D-1");
            Deal d = offer("D-1", 120, 1);
            rejected(apply("D-1", new PostOffer("R1", 119.9, d.version()), 2), ErrorCode.PRICE_NOT_CONCEDED);
        }

        @Test
        @DisplayName("§8-7 밴드 상한 초과: OUT_OF_BAND")
        void s07_aboveBand() {
            open("D-1");
            online("DR1");
            rejected(apply("D-1", new PlaceBid("DR1", 300.01, 12.98, 77.60, 1L), 1), ErrorCode.OUT_OF_BAND);
            rejected(apply("D-1", new PostOffer("R1", 300.01, 1L), 1), ErrorCode.OUT_OF_BAND);
        }

        @Test
        @DisplayName("§8-8 밴드 하한 미달: OUT_OF_BAND")
        void s08_belowBand() {
            open("D-1");
            online("DR1");
            rejected(apply("D-1", new PlaceBid("DR1", 69.99, 12.98, 77.60, 1L), 1), ErrorCode.OUT_OF_BAND);
            rejected(apply("D-1", new PostOffer("R1", 69.99, 1L), 1), ErrorCode.OUT_OF_BAND);
        }

        @Test
        @DisplayName("§8-9 기사 2명이 같은 nowMs에 승객 오퍼 수락: 1건만 MATCHED, 나머지 DEAL_ALREADY_MATCHED")
        void s09_twoDriversTakeOffer() {
            open("D-1");
            online("DR1", "DR2");
            Deal d = offer("D-1", 120, 1);
            MarketOutcome first = ok(apply("D-1", new AcceptOffer("DR1", d.version()), 5));
            MarketOutcome second = rejected(apply("D-1", new AcceptOffer("DR2", d.version()), 5), ErrorCode.DEAL_ALREADY_MATCHED);
            assertThat(events(first, "D-1")).filteredOn(e -> e instanceof DealMatched).hasSize(1);
            assertThat(second.events()).isEmpty();
            assertThat(deal("D-1").match().driverId()).isEqualTo("DR1");
        }

        @Test
        @DisplayName("§8-10 승객 지목 수락과 기사 선착 수락이 같은 nowMs: 어느 순서든 1건만 MATCHED")
        void s10_riderAndDriverAcceptTogether() {
            // rider first
            open("D-1");
            online("DR1", "DR2");
            Deal d = bid("D-1", "DR1", 150, 1);
            d = offer("D-1", 120, 2);
            ok(apply("D-1", new AcceptBid("R1", bidOf(d, "DR1").bidId(), d.version()), 5));
            rejected(apply("D-1", new AcceptOffer("DR2", d.version()), 5), ErrorCode.DEAL_ALREADY_MATCHED);
            assertThat(deal("D-1").match().matchPath()).isEqualTo(MatchPath.RIDER_PICKED_BID);

            // driver first
            open("D-2", "R2", 12.9716, 77.5946, 100.0, 0);
            online("DR3", "DR4");
            Deal e = bid("D-2", "DR3", 150, 1);
            e = offer("D-2", 120, 2);
            ok(apply("D-2", new AcceptOffer("DR4", e.version()), 5));
            rejected(apply("D-2", new AcceptBid("R2", bidOf(e, "DR3").bidId(), e.version()), 5), ErrorCode.DEAL_ALREADY_MATCHED);
            assertThat(deal("D-2").match().matchPath()).isEqualTo(MatchPath.DRIVER_TOOK_OFFER);
        }

        @Test
        @DisplayName("§8-11 승객 오퍼 TTL 만료 후(스윕 전) 기사 수락: OFFER_EXPIRED")
        void s11_expiredOfferBeforeSweep() {
            open("D-1");
            online("DR1");
            Deal d = offer("D-1", 120, 0);
            rejected(apply("D-1", new AcceptOffer("DR1", d.version()), 30), ErrorCode.OFFER_EXPIRED);
            assertThat(deal("D-1").offer()).as("removed only by the sweep").isNotNull();
        }

        @Test
        @DisplayName("§8-12 기사 이중 체결 차단: 타 거래 호가 전부 철회(DRIVER_MATCHED_ELSEWHERE), 이후 그 기사는 DRIVER_NOT_AVAILABLE")
        void s12_doubleMatchBlocked() {
            for (String id : List.of("D-1", "D-2", "D-3", "D-4")) open(id);
            online("DR1", "DR2");
            bid("D-1", "DR1", 150, 1);
            bid("D-2", "DR1", 150, 1);
            bid("D-3", "DR1", 150, 1);
            bid("D-2", "DR2", 160, 1);
            long v2 = deal("D-2").version();
            long v3 = deal("D-3").version();

            Deal d1 = deal("D-1");
            MarketOutcome r = ok(apply("D-1", new AcceptBid("R1", bidOf(d1, "DR1").bidId(), d1.version()), 2));
            assertThat(r.events().keySet()).containsExactly("D-1", "D-2", "D-3");
            for (String id : List.of("D-2", "D-3")) {
                assertThat(events(r, id)).singleElement().satisfies(e -> {
                    assertThat(((BidWithdrawn) e).driverId()).isEqualTo("DR1");
                    assertThat(((BidWithdrawn) e).reason()).isEqualTo(WithdrawReason.DRIVER_MATCHED_ELSEWHERE);
                });
            }
            assertThat(deal("D-2").bids()).extracting(Deal.Bid::driverId).containsExactly("DR2");
            assertThat(deal("D-3").bids()).isEmpty();
            assertThat(deal("D-2").version()).isEqualTo(v2 + 1);
            assertThat(deal("D-3").version()).isEqualTo(v3 + 1);
            assertThat(deal("D-2").withdrawCount()).isZero();
            assertThat(cmd.scard("driver:DR1:deals")).isZero();

            rejected(apply("D-4", new PlaceBid("DR1", 140, 12.98, 77.60, 1L), 3), ErrorCode.DRIVER_NOT_AVAILABLE);
        }

        @Test
        @DisplayName("§8-14 거래 TTL 만료 → 스윕: EXPIRED(TTL) (활성 호가 있어도)")
        void s14_ttlWithLiveBids() {
            open("D-1");
            online("DR1", "DR2");
            bid("D-1", "DR1", 150, 1);
            bid("D-1", "DR2", 140, 2);
            MarketOutcome r = ok(market.sweep(at(180)));
            assertThat(events(r, "D-1")).singleElement().satisfies(e ->
                    assertThat(((DealExpired) e).reason()).isEqualTo(EndReason.TTL));
            assertThat(r.closed()).containsExactly("D-1");
            assertThat(r.closedAt()).isEqualTo(at(180));
            Deal d = deal("D-1");
            assertThat(d.status()).isEqualTo(DealStatus.EXPIRED);
            assertThat(d.endReason()).isEqualTo(EndReason.TTL);
            assertThat(d.bids()).isEmpty();
        }

        @Test
        @DisplayName("§8-15 라운드 20 도달 후 21번째 행위: 미반영, ROUND_LIMIT_EXCEEDED(요청자), EXPIRED(ROUND_LIMIT)")
        void s15_roundLimit() {
            open("D-1");
            online("DR1");
            for (int i = 0; i < 20; i++) {
                if (i % 2 == 0) bid("D-1", "DR1", 250 - i, i + 1);
                else offer("D-1", 100 + i, i + 1);
            }
            Deal d = deal("D-1");
            assertThat(d.round()).isEqualTo(20);

            MarketOutcome r = ok(apply("D-1", new PostOffer("R1", 150, d.version()), 30));
            assertThat(r.requesterErrorCode()).isEqualTo(ErrorCode.ROUND_LIMIT_EXCEEDED);
            assertThat(events(r, "D-1")).singleElement().satisfies(e ->
                    assertThat(((DealExpired) e).reason()).isEqualTo(EndReason.ROUND_LIMIT));
            Deal after = deal("D-1");
            assertThat(after.status()).isEqualTo(DealStatus.EXPIRED);
            assertThat(after.round()).isEqualTo(20);
            assertThat(after.lastOfferPrice()).as("the 21st offer was not applied").isEqualTo(119);
            assertThat(after.offer()).isNull();
            assertThat(after.bids()).isEmpty();
        }

        @Test
        @DisplayName("§8-16 승객 취소: CANCELLED, 전 호가 철회")
        void s16_cancel() {
            open("D-1");
            online("DR1", "DR2");
            bid("D-1", "DR1", 150, 1);
            bid("D-1", "DR2", 140, 2);
            offer("D-1", 120, 3);
            MarketOutcome r = ok(apply("D-1", new Cancel("R1"), 4));
            assertThat(((DealExpired) first(r, "D-1")).reason()).isEqualTo(EndReason.CANCELLED_BY_RIDER);
            assertThat(r.closed()).containsExactly("D-1");
            Deal d = deal("D-1");
            assertThat(d.status()).isEqualTo(DealStatus.CANCELLED);
            assertThat(d.bids()).isEmpty();
            assertThat(d.offer()).isNull();
            assertThat(activeBidIndexed("DR1", "D-1")).isFalse();
            assertThat(activeBidIndexed("DR2", "D-1")).isFalse();
        }

        @Test
        @DisplayName("§8-18 철회 후 재입찰: 라운드 1만 증가(철회 미포함), R1은 직전 호가 기준 유지")
        void s18_withdrawAndRebid() {
            open("D-1");
            online("DR1");
            Deal d = bid("D-1", "DR1", 150, 1);
            assertThat(d.round()).isEqualTo(1);
            ok(apply("D-1", new WithdrawBid("DR1", d.version()), 2));
            d = deal("D-1");
            assertThat(d.round()).isEqualTo(1);
            rejected(apply("D-1", new PlaceBid("DR1", 155, 12.98, 77.60, d.version()), 3), ErrorCode.PRICE_NOT_CONCEDED);
            d = bid("D-1", "DR1", 150, 4);
            assertThat(d.round()).isEqualTo(2);
            assertThat(d.lastBidByDriver()).containsEntry("DR1", 150.0);
        }

        @Test
        @DisplayName("§8-19 기사가 50건에 호가한 상태에서 51번째 거래에 호가: MAX_ACTIVE_BIDS_EXCEEDED, 50건 유지, 기존 거래 가격 갱신은 정상")
        void s19_maxActiveBids() {
            online("DR1");
            for (int i = 1; i <= 51; i++) open(String.format("D-%02d", i));
            for (int i = 1; i <= 50; i++) bid(String.format("D-%02d", i), "DR1", 150, 1);
            assertThat(cmd.scard("driver:DR1:deals")).isEqualTo(50);

            rejected(apply("D-51", new PlaceBid("DR1", 150, 12.98, 77.60, 1L), 2), ErrorCode.MAX_ACTIVE_BIDS_EXCEEDED);
            assertThat(cmd.scard("driver:DR1:deals")).isEqualTo(50);

            Deal updated = bid("D-01", "DR1", 140, 3);
            assertThat(bidOf(updated, "DR1").price()).isEqualTo(140);
            assertThat(cmd.scard("driver:DR1:deals")).isEqualTo(50);
        }
    }

    // =============================================================================================
    // (c)-(j)
    // =============================================================================================

    @Test
    @DisplayName("(c) R13: 50건 상한, 갱신은 통과, 철회하면 51번째 성공, 철회 후 재호가도 검사, 체결되면 SCARD 0")
    void r13_maxActiveBids() {
        online("DR1");
        for (int i = 1; i <= 51; i++) open(String.format("D-%02d", i));
        for (int i = 1; i <= 50; i++) bid(String.format("D-%02d", i), "DR1", 150, 1);

        Map<String, String> before = cmd.hgetall("deal:D-51");
        rejected(apply("D-51", new PlaceBid("DR1", 150, 12.98, 77.60, 1L), 2), ErrorCode.MAX_ACTIVE_BIDS_EXCEEDED);
        assertThat(cmd.hgetall("deal:D-51")).isEqualTo(before);
        bid("D-02", "DR1", 145, 2);   // price update on a live bid: not counted

        ok(apply("D-01", new WithdrawBid("DR1", deal("D-01").version()), 3));
        assertThat(cmd.scard("driver:DR1:deals")).isEqualTo(49);
        bid("D-51", "DR1", 150, 4);
        assertThat(cmd.scard("driver:DR1:deals")).isEqualTo(50);

        // Re-bidding where the bid was withdrawn is a new live bid (SISMEMBER = 0): checked again.
        rejected(apply("D-01", new PlaceBid("DR1", 150, 12.98, 77.60, deal("D-01").version()), 5),
                ErrorCode.MAX_ACTIVE_BIDS_EXCEEDED);

        Deal d51 = deal("D-51");
        ok(apply("D-51", new AcceptBid("R1", bidOf(d51, "DR1").bidId(), d51.version()), 6));
        assertThat(cmd.scard("driver:DR1:deals")).isZero();
    }

    @Test
    @DisplayName("(d) 종료 정리: 만료·취소·체결 뒤 그 거래의 모든 입찰 기사 driver:{id}:deals에 그 거래가 없다")
    void closingCleansDriverSets() {
        open("D-EXP");
        open("D-CAN");
        open("D-MAT");
        online("DR1", "DR2", "DR3", "DR4");
        for (String id : List.of("D-EXP", "D-CAN")) {
            bid(id, "DR1", 150, 1);
            bid(id, "DR2", 140, 1);
        }
        bid("D-MAT", "DR3", 150, 1);
        bid("D-MAT", "DR4", 140, 1);

        ok(apply("D-CAN", new Cancel("R1"), 2));
        Deal mat = deal("D-MAT");
        ok(apply("D-MAT", new AcceptBid("R1", bidOf(mat, "DR3").bidId(), mat.version()), 3));
        ok(market.sweep(at(180)));

        for (String driver : List.of("DR1", "DR2")) {
            assertThat(activeBidIndexed(driver, "D-EXP")).isFalse();
            assertThat(activeBidIndexed(driver, "D-CAN")).isFalse();
        }
        assertThat(activeBidIndexed("DR3", "D-MAT")).isFalse();
        assertThat(activeBidIndexed("DR4", "D-MAT")).isFalse();
        assertThat(cmd.scard("driver:DR1:deals") + cmd.scard("driver:DR2:deals") + cmd.scard("driver:DR4:deals")).isZero();
        assertThat(cmd.zscore("deals:expiry", "D-MAT")).isNull();
        assertThat(cmd.geopos("geo:deals", "D-CAN").get(0)).isNull();
    }

    @Test
    @DisplayName("(e) 결정성: 같은 명령열을 FLUSHDB 후 두 번 실행하면 각 스크립트의 반환 문자열이 바이트 단위로 같다")
    void deterministicReplies() {
        LuaScripts scripts = new LuaScripts(cmd);
        List<String> firstRun = script(scripts);
        market.flushDb();
        List<String> secondRun = script(scripts);
        assertThat(secondRun).isEqualTo(firstRun);
        assertThat(firstRun).allSatisfy(reply -> assertThat(reply).startsWith("{"));
    }

    private List<String> script(LuaScripts s) {
        long t = T0.toEpochMilli();
        List<String> out = new ArrayList<>();
        for (String[] deal : new String[][]{{"D-1", "R1", "12.9716", "77.5946"}, {"D-2", "R2", "12.93", "77.62"}}) {
            out.add(s.call("create_deal", ms(t), deal[0], deal[1], deal[2], deal[3], "100.0", "180000", "30000", "20",
                    "0.7", "3.0", "20.0", "1.3", "50", "60000", "{\"distanceKm\":8.42}"));
        }
        for (String driver : List.of("DR1", "DR2", "DR3")) {
            out.add(s.call("presence_upsert", ms(t), "DRIVER", driver, "3600000", "12.98", "77.6"));
        }
        out.add(s.call("place_bid", ms(t + 1000), "D-1", "DR1", "150.0", "12.98", "77.6", ""));
        out.add(s.call("place_bid", ms(t + 1000), "D-1", "DR2", "130.0", "12.9401", "77.6102", ""));
        out.add(s.call("place_bid", ms(t + 2000), "D-2", "DR1", "140.0", "12.98", "77.6", ""));
        out.add(s.call("place_bid", ms(t + 2000), "D-2", "DR3", "140.0", "12.972", "77.5951", ""));
        out.add(s.call("post_offer", ms(t + 3000), "D-1", "R1", "120.0", ""));
        out.add(s.call("withdraw_bid", ms(t + 4000), "D-1", "DR2", ""));
        out.add(s.call("get_deal", ms(t + 4000), "D-1"));
        out.add(s.call("get_deal", ms(t + 4000), "D-2"));
        out.add(s.call("accept_bid", ms(t + 5000), "D-1", "R1", "B-001", ""));
        out.add(s.call("get_deal", ms(t + 5000), "D-2"));
        out.add(s.call("post_offer", ms(t + 6000), "D-2", "R2", "110.0", ""));
        out.add(s.call("sweep", ms(t + 36000), "1000", "60000"));
        out.add(s.call("sweep", ms(t + 180000), "1000", "60000"));
        out.add(s.call("get_deal", ms(t + 180000), "D-2"));
        out.add(s.call("sweep", ms(t + 300000), "1000", "60000"));
        return out;
    }

    private static String ms(long epochMs) {
        return Long.toString(epochMs);
    }

    @Test
    @DisplayName("(f) purge: createdAt + 300초 스윕 뒤 거래 키 3개가 없고 get_deal은 DEAL_NOT_ACTIVE, 체결 기사는 MATCHED가 풀려 다시 호가할 수 있다")
    void purgeReleasesWinner() {
        open("D-1");
        online("DR1");
        Deal d = bid("D-1", "DR1", 150, 1);
        ok(apply("D-1", new AcceptBid("R1", d.bids().get(0).bidId(), d.version()), 2));
        assertThat(cmd.geopos("geo:drivers", "DR1").get(0)).isNull();

        open("D-2", "R2", 12.9716, 77.5946, 100.0, 250);
        rejected(apply("D-2", new PlaceBid("DR1", 150, 12.98, 77.60, 1L), 260), ErrorCode.DRIVER_NOT_AVAILABLE);

        ok(market.sweep(at(299)));
        assertThat(market.snapshot("D-1", at(299))).isPresent();

        ok(market.sweep(at(300)));
        assertThat(market.snapshot("D-1", at(300))).isEmpty();
        MarketOutcome gone = new LuaResultParser().outcome(new LuaScripts(cmd).call("get_deal", ms(at(300).toEpochMilli()), "D-1"));
        assertThat(gone.code()).isEqualTo(ErrorCode.DEAL_NOT_ACTIVE);
        assertThat(gone.version()).isZero();
        assertThat(cmd.exists("deal:D-1", "deal:D-1:bids", "deal:D-1:lastBid")).isZero();
        assertThat(cmd.exists("driver:DR1:state")).isZero();
        assertThat(cmd.geopos("geo:drivers", "DR1").get(0)).as("back in supply (presence still alive)").isNotNull();

        ok(apply("D-2", new PlaceBid("DR1", 150, 12.98, 77.60, 1L), 301));
    }

    @Test
    @DisplayName("(f') purge 시각에 아직 열려 있는 거래는 먼저 EXPIRED(TTL)로 닫힌 뒤 지워진다")
    void purgeClosesStillOpenDeal() {
        DealRules longTtl = new DealRules(0.7, 3.0, Duration.ofSeconds(400), Duration.ofSeconds(30), 20, 20.0, 1.3,
                50, Duration.ofSeconds(60));
        RedisMarket m = new RedisMarket(cmd, db, longTtl);
        m.createDeal("D-1", "R1", 12.9716, 77.5946, 100.0, Map.of(), T0);
        online("DR1");
        ok(m.apply("D-1", new PlaceBid("DR1", 150, 12.98, 77.60, 1L), at(1)));

        MarketOutcome r = ok(m.sweep(at(300)));
        assertThat(events(r, "D-1")).singleElement().satisfies(e ->
                assertThat(((DealExpired) e).reason()).isEqualTo(EndReason.TTL));
        assertThat(r.closed()).containsExactly("D-1");
        assertThat(m.snapshot("D-1", at(300))).isEmpty();
        assertThat(activeBidIndexed("DR1", "D-1")).isFalse();
        assertThat(cmd.zscore("deals:expiry", "D-1")).isNull();
    }

    @Test
    @DisplayName("(g) 거부된 명령 뒤 거래 Hash(와 호가·lastBid)가 바뀌지 않는다")
    void rejectionChangesNothing() {
        open("D-1");
        online("DR1", "DR2");
        bid("D-1", "DR1", 150, 1);
        Deal d = offer("D-1", 120, 2);
        long v = d.version();
        String bidId = d.bids().get(0).bidId();

        Map<String, String> deal = cmd.hgetall("deal:D-1");
        Map<String, String> bids = cmd.hgetall("deal:D-1:bids");
        Map<String, String> lastBid = cmd.hgetall("deal:D-1:lastBid");

        List<Object[]> attempts = List.of(
                new Object[]{new PlaceBid("DR1", 160, 12.98, 77.60, v), 3, ErrorCode.PRICE_NOT_CONCEDED},
                new Object[]{new PlaceBid("DR2", 1000, 12.98, 77.60, v), 3, ErrorCode.OUT_OF_BAND},
                new Object[]{new PlaceBid("DR2", 130, 12.98, 77.60, v - 1), 3, ErrorCode.VERSION_CONFLICT},
                new Object[]{new PlaceBid("DR9", 130, 12.98, 77.60, v), 3, ErrorCode.DRIVER_NOT_AVAILABLE},
                new Object[]{new PlaceBid("DR2", 130, 12.98, 77.60, v), 180, ErrorCode.DEAL_NOT_ACTIVE},
                new Object[]{new PostOffer("R2", 130, v), 3, ErrorCode.NOT_DEAL_OWNER},
                new Object[]{new PostOffer("R1", 110, v), 3, ErrorCode.PRICE_NOT_CONCEDED},
                new Object[]{new WithdrawBid("DR2", v), 3, ErrorCode.BID_NOT_FOUND},
                new Object[]{new AcceptBid("R1", "B-999", v), 3, ErrorCode.BID_NOT_FOUND},
                new Object[]{new AcceptBid("R1", bidId, v - 1), 3, ErrorCode.VERSION_CONFLICT},
                new Object[]{new AcceptOffer("DR2", v), 40, ErrorCode.OFFER_EXPIRED},
                new Object[]{new Cancel("R2"), 3, ErrorCode.NOT_DEAL_OWNER});
        for (Object[] a : attempts) {
            MarketOutcome r = rejected(apply("D-1", (DealCommand) a[0], (Integer) a[1]), (ErrorCode) a[2]);
            assertThat(r.version()).isEqualTo(v);
            assertThat(cmd.hgetall("deal:D-1")).as("after %s", a[0]).isEqualTo(deal);
            assertThat(cmd.hgetall("deal:D-1:bids")).isEqualTo(bids);
            assertThat(cmd.hgetall("deal:D-1:lastBid")).isEqualTo(lastBid);
        }
    }

    @Test
    @DisplayName("(h) 빈 driverId → DRIVER_NOT_AVAILABLE, 빈 riderId → NOT_DEAL_OWNER")
    void emptyActorIds() {
        open("D-1");
        for (String none : new String[]{null, ""}) {
            rejected(apply("D-1", new PlaceBid(none, 150, 12.98, 77.60, 1L), 1), ErrorCode.DRIVER_NOT_AVAILABLE);
            rejected(apply("D-1", new WithdrawBid(none, 1L), 1), ErrorCode.DRIVER_NOT_AVAILABLE);
            rejected(apply("D-1", new AcceptOffer(none, 1L), 1), ErrorCode.DRIVER_NOT_AVAILABLE);
            rejected(apply("D-1", new PostOffer(none, 150, 1L), 1), ErrorCode.NOT_DEAL_OWNER);
            rejected(apply("D-1", new AcceptBid(none, "B-001", 1L), 1), ErrorCode.NOT_DEAL_OWNER);
            rejected(apply("D-1", new Cancel(none), 1), ErrorCode.NOT_DEAL_OWNER);
        }
    }

    @Test
    @DisplayName("(i) 이벤트가 없는 결과(create_deal, 빈 sweep)는 Java에서 빈 목록으로 읽힌다")
    void emptyResultsParseAsEmptyLists() {
        String raw = new LuaScripts(cmd).call("create_deal", ms(T0.toEpochMilli()), "D-1", "R1", "12.9716", "77.5946",
                "100.0", "180000", "30000", "20", "0.7", "3.0", "20.0", "1.3", "50", "60000", "{}");
        assertThat(raw).contains("\"events\":{}");   // cjson writes an empty Lua table as an object
        MarketOutcome created = new LuaResultParser().outcome(raw);
        assertThat(created.ok()).isTrue();
        assertThat(created.events()).isEmpty();
        assertThat(created.closed()).isEmpty();
        assertThat(created.closedAt()).isNull();
        assertThat(created.requesterErrorCode()).isNull();

        MarketOutcome swept = ok(market.sweep(at(1)));
        assertThat(swept.events()).isEmpty();
        assertThat(swept.closed()).isEmpty();
    }

    @Test
    @DisplayName("(j) 라운드 상한 결과: ok:true + deal.expired(ROUND_LIMIT) + requesterError(ROUND_LIMIT_EXCEEDED), round는 20 그대로")
    void roundLimitReplyShape() {
        open("D-1");
        online("DR1", "DR2");
        for (int i = 0; i < 20; i++) bid("D-1", i % 2 == 0 ? "DR1" : "DR2", 250 - i, i + 1);
        Deal d = deal("D-1");

        MarketOutcome r = ok(apply("D-1", new PlaceBid("DR2", 200, 12.98, 77.60, d.version()), 30));
        Deal after = deal("D-1");
        assertThat(r.ok()).isTrue();
        assertThat(events(r, "D-1")).singleElement().satisfies(e -> {
            assertThat(((DealExpired) e).reason()).isEqualTo(EndReason.ROUND_LIMIT);
            assertThat(e.version()).isEqualTo(after.version());
        });
        assertThat(r.closed()).containsExactly("D-1");
        assertThat(r.closedAt()).isEqualTo(at(30));
        assertThat(r.requesterErrorCode()).isEqualTo(ErrorCode.ROUND_LIMIT_EXCEEDED);
        assertThat(r.requesterErrorMessage()).isEqualTo("라운드 상한(20회)을 넘어 거래가 종료되었습니다");
        assertThat(r.requesterErrorVersion()).isEqualTo(d.version() + 1).isEqualTo(after.version());
        assertThat(after.round()).isEqualTo(20);
        assertThat(after.bids()).isEmpty();
        assertThat(cmd.scard("driver:DR1:deals") + cmd.scard("driver:DR2:deals")).isZero();
    }
}
