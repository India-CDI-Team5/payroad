package com.cdi.dynamicpayroad.domain;

import com.cdi.dynamicpayroad.domain.DealCommand.AcceptBid;
import com.cdi.dynamicpayroad.domain.DealCommand.PlaceBid;
import com.cdi.dynamicpayroad.domain.DealEvent.BidWithdrawn;
import com.cdi.dynamicpayroad.domain.DealEvent.DealMatched;
import com.cdi.dynamicpayroad.domain.Enums.DriverStatus;
import com.cdi.dynamicpayroad.domain.Enums.WithdrawReason;
import com.cdi.dynamicpayroad.domain.MarketStateMachine.MarketResult;
import com.cdi.dynamicpayroad.domain.MarketStateMachine.MarketState;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/** Test 11 of the milestone: the rules that span deals. Fails until MarketStateMachine is implemented. */
class MarketStateMachineTest {

    static final Instant T0 = Instant.parse("2026-10-01T00:00:00Z");
    static final DealRules RULES = DealRules.defaults();
    final MarketStateMachine market = new MarketStateMachine(new DealStateMachine(RULES));

    static MarketResult.Accepted ok(MarketResult r) {
        assertThat(r).isInstanceOf(MarketResult.Accepted.class);
        return (MarketResult.Accepted) r;
    }

    static void rejected(MarketResult r, ErrorCode code) {
        assertThat(r).isInstanceOf(MarketResult.Rejected.class);
        assertThat(((MarketResult.Rejected) r).code()).isEqualTo(code);
    }

    MarketState bid(MarketState m, String dealId, String driver, double price) {
        long v = m.deals().get(dealId).version();
        return ok(market.apply(m, dealId, new PlaceBid(driver, price, 12.98, 77.60, v), T0.plusSeconds(1))).state();
    }

    @Test
    @DisplayName("11. R10·R11 이중 체결 차단: 체결된 기사의 다른 호가는 즉시 철회되고, 이후 그 기사와 오프라인 기사는 DRIVER_NOT_AVAILABLE")
    void doubleMatchBlocked() {
        MarketState m = new MarketState(
                Map.of("D-1", Deal.open("D-1", "R1", 12.97, 77.59, 100, T0, RULES),
                       "D-2", Deal.open("D-2", "R2", 12.93, 77.62, 100, T0, RULES),
                       "D-3", Deal.open("D-3", "R3", 12.95, 77.60, 100, T0, RULES)),
                Map.of("DR1", DriverStatus.ONLINE, "DR2", DriverStatus.ONLINE));
        m = bid(m, "D-1", "DR1", 150);
        m = bid(m, "D-2", "DR1", 140);
        m = bid(m, "D-2", "DR2", 160);

        Deal d1 = m.deals().get("D-1");
        MarketResult.Accepted r = ok(market.apply(m, "D-1",
                new AcceptBid("R1", d1.bids().get(0).bidId(), d1.version()), T0.plusSeconds(5)));

        assertThat(r.events().get("D-1")).anySatisfy(e -> assertThat(e).isInstanceOf(DealMatched.class));
        assertThat(r.events().get("D-2")).singleElement().satisfies(e -> {
            assertThat(e).isInstanceOf(BidWithdrawn.class);
            assertThat(((BidWithdrawn) e).driverId()).isEqualTo("DR1");
            assertThat(((BidWithdrawn) e).reason()).isEqualTo(WithdrawReason.DRIVER_MATCHED_ELSEWHERE);
        });
        assertThat(r.state().deals().get("D-2").bids()).extracting(Deal.Bid::driverId).containsExactly("DR2");
        assertThat(r.state().drivers().get("DR1")).isEqualTo(DriverStatus.MATCHED);

        MarketState after = r.state();
        long v3 = after.deals().get("D-3").version();
        rejected(market.apply(after, "D-3", new PlaceBid("DR1", 130, 12.98, 77.60, v3), T0.plusSeconds(6)),
                ErrorCode.DRIVER_NOT_AVAILABLE);
        rejected(market.apply(after, "D-3", new PlaceBid("DR9", 130, 12.98, 77.60, v3), T0.plusSeconds(6)),
                ErrorCode.DRIVER_NOT_AVAILABLE);
    }
}
