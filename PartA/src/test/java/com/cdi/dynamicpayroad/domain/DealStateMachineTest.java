package com.cdi.dynamicpayroad.domain;

import com.cdi.dynamicpayroad.domain.DealCommand.AcceptBid;
import com.cdi.dynamicpayroad.domain.DealCommand.AcceptOffer;
import com.cdi.dynamicpayroad.domain.DealCommand.Cancel;
import com.cdi.dynamicpayroad.domain.DealCommand.PlaceBid;
import com.cdi.dynamicpayroad.domain.DealCommand.PostOffer;
import com.cdi.dynamicpayroad.domain.DealCommand.Tick;
import com.cdi.dynamicpayroad.domain.DealCommand.WithdrawBid;
import com.cdi.dynamicpayroad.domain.DealEvent.BidPlaced;
import com.cdi.dynamicpayroad.domain.DealEvent.BidUpdated;
import com.cdi.dynamicpayroad.domain.DealEvent.BidWithdrawn;
import com.cdi.dynamicpayroad.domain.DealEvent.DealExpired;
import com.cdi.dynamicpayroad.domain.DealEvent.DealMatched;
import com.cdi.dynamicpayroad.domain.DealEvent.OfferExpired;
import com.cdi.dynamicpayroad.domain.DealEvent.OfferPosted;
import com.cdi.dynamicpayroad.domain.DealStateMachine.DriverAvailability;
import com.cdi.dynamicpayroad.domain.Enums.EndReason;
import com.cdi.dynamicpayroad.domain.Enums.MatchPath;
import com.cdi.dynamicpayroad.domain.Enums.PendingSide;
import com.cdi.dynamicpayroad.domain.Enums.WithdrawReason;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * The 12 rule tests of the milestone (11 here, R10/R11 in MarketStateMachineTest).
 * They describe api-spec v1.1 and fail until DealStateMachine is implemented.
 *
 * Fixture: basePrice 100 -> band [70, 300]; deal created at T0, TTL 180 s, offer TTL 30 s.
 */
class DealStateMachineTest {

    static final Instant T0 = Instant.parse("2026-10-01T00:00:00Z");
    static final DealRules RULES = DealRules.defaults();
    final DealStateMachine sm = new DealStateMachine(RULES);

    Deal fresh() {
        return Deal.open("D-1", "R1", 12.9716, 77.5946, 100.0, T0, RULES);
    }

    Result apply(Deal deal, DealCommand cmd, int secondsAfterT0) {
        return sm.apply(deal, cmd, DriverAvailability.ALL, T0.plusSeconds(secondsAfterT0));
    }

    static Result.Accepted ok(Result r) {
        assertThat(r).as("expected the command to be accepted").isInstanceOf(Result.Accepted.class);
        return (Result.Accepted) r;
    }

    static void rejected(Result r, ErrorCode code) {
        assertThat(r).isInstanceOf(Result.Rejected.class);
        assertThat(((Result.Rejected) r).code()).isEqualTo(code);
    }

    /** A bid placed 1 km-ish from the origin, with the deal's current version. */
    Deal bid(Deal d, String driver, double price, int t) {
        return ok(apply(d, new PlaceBid(driver, price, 12.98, 77.60, d.version()), t)).deal();
    }

    @Test
    @DisplayName("1. 정상 협상: 호가 2건 -> 승객이 비싼 호가를 지목 -> MATCHED, chosenRank = 2")
    void riderPicksBid() {
        Deal d = bid(fresh(), "DR1", 150, 5);
        assertThat(d.status()).isEqualTo(DealStatus.NEGOTIATING);
        assertThat(d.pendingSide()).isEqualTo(PendingSide.RIDER);
        d = bid(d, "DR2", 130, 6);
        assertThat(d.round()).isEqualTo(2);
        assertThat(d.version()).isEqualTo(3);
        String pricier = d.bids().stream().filter(b -> b.driverId().equals("DR1")).findFirst().orElseThrow().bidId();

        Result.Accepted r = ok(apply(d, new AcceptBid("R1", pricier, d.version()), 10));
        assertThat(r.deal().status()).isEqualTo(DealStatus.MATCHED);
        DealMatched m = (DealMatched) r.events().get(0);
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
        rejected(apply(fresh(), new AcceptOffer("DR1", 1L), 1), ErrorCode.OFFER_NOT_FOUND);

        Result.Accepted posted = ok(apply(fresh(), new PostOffer("R1", 120, 1L), 2));
        assertThat(posted.events().get(0)).isInstanceOf(OfferPosted.class);
        assertThat(posted.deal().pendingSide()).isEqualTo(PendingSide.DRIVER);

        Deal d = posted.deal();
        Result.Accepted r = ok(apply(d, new AcceptOffer("DR1", d.version()), 10));
        DealMatched m = (DealMatched) r.events().get(0);
        assertThat(m.match().finalPrice()).isEqualTo(120);
        assertThat(m.match().matchPath()).isEqualTo(MatchPath.DRIVER_TOOK_OFFER);
        assertThat(r.deal().status()).isEqualTo(DealStatus.MATCHED);
    }

    @Test
    @DisplayName("3. R1 기사 단조성: 자기 직전 호가보다 올릴 수 없고, 철회 후 재입찰해도 기준이 유지된다")
    void driverMonotonic() {
        Deal d = bid(fresh(), "DR1", 150, 1);
        rejected(apply(d, new PlaceBid("DR1", 160, 12.98, 77.60, d.version()), 2), ErrorCode.PRICE_NOT_CONCEDED);

        Result.Accepted lower = ok(apply(d, new PlaceBid("DR1", 140, 12.98, 77.60, d.version()), 3));
        assertThat(lower.events().get(0)).isInstanceOf(BidUpdated.class);
        d = lower.deal();

        // Another driver may bid above the current lowest: R1 compares a driver only with himself.
        d = bid(d, "DR2", 200, 4);

        d = ok(apply(d, new WithdrawBid("DR1", d.version()), 5)).deal();
        rejected(apply(d, new PlaceBid("DR1", 145, 12.98, 77.60, d.version()), 6), ErrorCode.PRICE_NOT_CONCEDED);
        ok(apply(d, new PlaceBid("DR1", 140, 12.98, 77.60, d.version()), 7));   // equal is allowed
    }

    @Test
    @DisplayName("4. R1 승객 단조성 + 소유권: 오퍼는 낮출 수 없고, 남의 거래에는 낼 수 없다")
    void riderMonotonicAndOwner() {
        Deal d = ok(apply(fresh(), new PostOffer("R1", 110, 1L), 1)).deal();
        rejected(apply(d, new PostOffer("R1", 100, d.version()), 2), ErrorCode.PRICE_NOT_CONCEDED);
        ok(apply(d, new PostOffer("R1", 115, d.version()), 3));
        rejected(apply(d, new PostOffer("R2", 115, d.version()), 4), ErrorCode.NOT_DEAL_OWNER);
    }

    @Test
    @DisplayName("5. R2 호가 밴드: basePrice x [0.7, 3.0] 밖은 OUT_OF_BAND, 경계값은 허용")
    void band() {
        Deal d = fresh();
        rejected(apply(d, new PlaceBid("DR1", 69.99, 12.98, 77.60, 1L), 1), ErrorCode.OUT_OF_BAND);
        rejected(apply(d, new PlaceBid("DR1", 300.01, 12.98, 77.60, 1L), 1), ErrorCode.OUT_OF_BAND);
        rejected(apply(d, new PostOffer("R1", 60, 1L), 1), ErrorCode.OUT_OF_BAND);
        d = bid(d, "DR1", 70, 2);
        bid(d, "DR2", 300, 3);
    }

    @Test
    @DisplayName("6. R5 호가 대체·철회: 기사당 1건, 철회는 라운드에 안 들어가고, 철회된 호가는 지목할 수 없다")
    void replaceAndWithdraw() {
        Deal d = bid(fresh(), "DR1", 150, 1);
        String oldBidId = d.bids().get(0).bidId();
        d = bid(d, "DR1", 140, 2);
        assertThat(d.bids()).hasSize(1);
        int roundBefore = d.round();

        Result.Accepted w = ok(apply(d, new WithdrawBid("DR1", d.version()), 3));
        BidWithdrawn e = (BidWithdrawn) w.events().get(0);
        assertThat(e.reason()).isEqualTo(WithdrawReason.BY_DRIVER);
        assertThat(w.deal().round()).isEqualTo(roundBefore);
        assertThat(w.deal().withdrawCount()).isEqualTo(1);
        assertThat(w.deal().bids()).isEmpty();

        rejected(apply(w.deal(), new AcceptBid("R1", oldBidId, w.deal().version()), 4), ErrorCode.BID_NOT_FOUND);
    }

    @Test
    @DisplayName("7. R6 오퍼 TTL 30초: 지나면 수락은 OFFER_EXPIRED, Tick은 offer.expired를 내고 pendingSide = RIDER")
    void offerTtl() {
        Deal d = ok(apply(fresh(), new PostOffer("R1", 120, 1L), 0)).deal();
        rejected(apply(d, new AcceptOffer("DR1", d.version()), 31), ErrorCode.OFFER_EXPIRED);

        Result.Accepted t = ok(apply(d, new Tick(), 31));
        assertThat(t.events()).singleElement().isInstanceOf(OfferExpired.class);
        assertThat(t.deal().offer()).isNull();
        assertThat(t.deal().pendingSide()).isEqualTo(PendingSide.RIDER);
    }

    @Test
    @DisplayName("8. R7 거래 TTL 180초: 179초엔 변화 없음, 180초에 EXPIRED(TTL), 이후 행위는 DEAL_NOT_ACTIVE")
    void dealTtl() {
        Deal d = bid(fresh(), "DR1", 150, 1);
        Result.Accepted before = ok(apply(d, new Tick(), 179));
        assertThat(before.events()).isEmpty();
        assertThat(before.deal().version()).isEqualTo(d.version());

        Result.Accepted at = ok(apply(d, new Tick(), 180));
        assertThat(at.deal().status()).isEqualTo(DealStatus.EXPIRED);
        assertThat(((DealExpired) at.events().get(0)).reason()).isEqualTo(EndReason.TTL);

        rejected(apply(at.deal(), new PlaceBid("DR2", 120, 12.98, 77.60, at.deal().version()), 181), ErrorCode.DEAL_NOT_ACTIVE);

        // A deal with no bids at all expires the same way.
        assertThat(ok(apply(fresh(), new Tick(), 180)).deal().status()).isEqualTo(DealStatus.EXPIRED);
    }

    @Test
    @DisplayName("9. R8 라운드 상한 20: 21번째 행위는 반영되지 않고 거래가 EXPIRED(ROUND_LIMIT)")
    void roundLimit() {
        Deal d = fresh();
        for (int i = 0; i < 20; i++) {
            d = bid(d, i % 2 == 0 ? "DR1" : "DR2", 250 - i, i + 1);   // each driver keeps conceding
        }
        assertThat(d.round()).isEqualTo(20);

        // The service turns this result into a ROUND_LIMIT_EXCEEDED error for the requester.
        Result.Accepted r = ok(apply(d, new PlaceBid("DR1", 200, 12.98, 77.60, d.version()), 30));
        assertThat(r.deal().status()).isEqualTo(DealStatus.EXPIRED);
        assertThat(r.events()).singleElement().isInstanceOf(DealExpired.class);
        assertThat(((DealExpired) r.events().get(0)).reason()).isEqualTo(EndReason.ROUND_LIMIT);
        assertThat(r.deal().round()).isEqualTo(20);
    }

    @Test
    @DisplayName("10. R9 단일 체결 + version CAS: 같은 version의 두 수락 중 두 번째는 DEAL_ALREADY_MATCHED, 낡은 version은 VERSION_CONFLICT")
    void singleMatchAndVersion() {
        Deal d = bid(fresh(), "DR1", 150, 1);
        d = ok(apply(d, new PostOffer("R1", 120, d.version()), 2)).deal();
        long seen = d.version();
        String bidId = d.bids().get(0).bidId();

        Deal matched = ok(apply(d, new AcceptBid("R1", bidId, seen), 3)).deal();
        rejected(apply(matched, new AcceptOffer("DR2", seen), 3), ErrorCode.DEAL_ALREADY_MATCHED);

        rejected(apply(d, new PlaceBid("DR2", 130, 12.98, 77.60, seen - 1), 4), ErrorCode.VERSION_CONFLICT);
    }

    @Test
    @DisplayName("12. R12 승객 취소: 본인만 취소 가능, CANCELLED(CANCELLED_BY_RIDER) 후 호가 전부 철회, 이후 수락은 DEAL_NOT_ACTIVE")
    void cancel() {
        Deal d = bid(fresh(), "DR1", 150, 1);
        rejected(apply(d, new Cancel("R2"), 2), ErrorCode.NOT_DEAL_OWNER);

        Result.Accepted c = ok(apply(d, new Cancel("R1"), 3));
        assertThat(c.deal().status()).isEqualTo(DealStatus.CANCELLED);
        assertThat(c.deal().bids()).isEmpty();
        assertThat(c.events()).anySatisfy(e -> {
            assertThat(e).isInstanceOf(DealExpired.class);
            assertThat(((DealExpired) e).reason()).isEqualTo(EndReason.CANCELLED_BY_RIDER);
        });

        String bidId = d.bids().get(0).bidId();
        rejected(apply(c.deal(), new AcceptBid("R1", bidId, c.deal().version()), 4), ErrorCode.DEAL_NOT_ACTIVE);
    }

    @Test
    @DisplayName("(보조) R11 기사 자격·version: 자격 없는 기사는 DRIVER_NOT_AVAILABLE, 낡은 version은 VERSION_CONFLICT, 없는 호가 철회는 BID_NOT_FOUND")
    void driverEligibilityAndVersion() {
        Deal d = fresh();
        DriverAvailability onlyDr1 = id -> id.equals("DR1");
        Result offline = sm.apply(d, new PlaceBid("DR2", 150, 12.98, 77.60, d.version()), onlyDr1, T0);
        rejected(offline, ErrorCode.DRIVER_NOT_AVAILABLE);

        d = bid(d, "DR1", 150, 1);
        rejected(apply(d, new PlaceBid("DR1", 140, 12.98, 77.60, d.version() - 1), 2), ErrorCode.VERSION_CONFLICT);
        rejected(apply(d, new WithdrawBid("DR2", d.version()), 3), ErrorCode.BID_NOT_FOUND);

        // Rejections leave the deal untouched and report its current version.
        assertThat(((Result.Rejected) offline).version()).isEqualTo(1);
    }

    @Test
    @DisplayName("(보조) TTL이 지나면 Tick 전이라도 행동은 DEAL_NOT_ACTIVE, 오퍼 수락은 chosenRank 0과 수락 기사 자신의 픽업 거리를 기록")
    void ttlGapAndOfferMatchFields() {
        Deal d = bid(fresh(), "DR1", 150, 1);
        rejected(apply(d, new PlaceBid("DR2", 120, 12.98, 77.60, d.version()), 180), ErrorCode.DEAL_NOT_ACTIVE);

        d = bid(d, "DR2", 130, 2);
        d = ok(apply(d, new PostOffer("R1", 125, d.version()), 3)).deal();
        Deal.Match byBidder = ((DealMatched) ok(apply(d, new AcceptOffer("DR1", d.version()), 4)).events().get(0)).match();
        assertThat(byBidder.chosenRank()).isZero();
        assertThat(byBidder.finalPrice()).isEqualTo(125);
        assertThat(byBidder.lowestBidPrice()).isEqualTo(130);
        assertThat(byBidder.pickupDistanceKm()).isNotNull();

        Deal.Match byStranger = ((DealMatched) ok(apply(d, new AcceptOffer("DR9", d.version()), 4)).events().get(0)).match();
        assertThat(byStranger.pickupDistanceKm()).isNull();
    }

    @Test
    @DisplayName("(보조) 첫 호가는 bid.placed, 서버가 픽업 거리·ETA를 계산한다")
    void firstBidEvent() {
        Result.Accepted r = ok(apply(fresh(), new PlaceBid("DR1", 150, 12.98, 77.60, 1L), 1));
        BidPlaced e = (BidPlaced) r.events().get(0);
        assertThat(e.bid().pickupDistanceKm()).isGreaterThan(0);
        assertThat(e.bid().pickupEtaMin()).isEqualTo(RULES.pickupEtaMin(e.bid().pickupDistanceKm()));
        assertThat(e.bidderCount()).isEqualTo(1);
    }
}
