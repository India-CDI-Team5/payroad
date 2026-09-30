package com.cdi.dynamicpayroad.domain;

import com.cdi.dynamicpayroad.domain.Enums.DriverStatus;

import java.time.Instant;
import java.util.List;
import java.util.Map;

/**
 * Rules that span deals: R10 (a matched driver's other bids are withdrawn at once) and R11
 * (only ONLINE drivers may act). Delegates everything else to {@link DealStateMachine}.
 * Applying one command to the whole market in one step is what makes R9 and R10 atomic
 * on a single node (plan v4 §3.1).
 */
public final class MarketStateMachine {

    /** All deals plus driver presence. A driver missing from {@code drivers} is offline. */
    public record MarketState(Map<String, Deal> deals, Map<String, DriverStatus> drivers) {
        public MarketState {
            deals = Map.copyOf(deals);
            drivers = Map.copyOf(drivers);
        }
    }

    public sealed interface MarketResult {
        /** {@code events} per deal id, including deals touched only through R10. */
        record Accepted(MarketState state, Map<String, List<DealEvent>> events) implements MarketResult {}

        record Rejected(String dealId, ErrorCode code, String message, long version) implements MarketResult {}
    }

    private final DealStateMachine deals;

    public MarketStateMachine(DealStateMachine deals) {
        this.deals = deals;
    }

    public MarketResult apply(MarketState market, String dealId, DealCommand command, Instant now) {
        throw new UnsupportedOperationException("MarketStateMachine is not implemented yet (milestone 10/3)");
    }
}
