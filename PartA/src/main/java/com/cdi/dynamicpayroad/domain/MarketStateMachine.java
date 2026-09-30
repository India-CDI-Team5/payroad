package com.cdi.dynamicpayroad.domain;

import com.cdi.dynamicpayroad.domain.DealEvent.DealMatched;
import com.cdi.dynamicpayroad.domain.Enums.DriverStatus;
import com.cdi.dynamicpayroad.domain.Enums.WithdrawReason;

import java.time.Instant;
import java.util.HashMap;
import java.util.LinkedHashMap;
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
        /** {@code events} per deal id, only for deals that changed (including those touched through R10). */
        record Accepted(MarketState state, Map<String, List<DealEvent>> events) implements MarketResult {
            public Accepted {
                events = Map.copyOf(events);
            }
        }

        /** {@code version} is 0 when the deal does not exist. */
        record Rejected(String dealId, ErrorCode code, String message, long version) implements MarketResult {}
    }

    private final DealStateMachine deals;

    public MarketStateMachine(DealStateMachine deals) {
        this.deals = deals;
    }

    public MarketResult apply(MarketState market, String dealId, DealCommand command, Instant now) {
        Deal deal = market.deals().get(dealId);
        if (deal == null) {
            return new MarketResult.Rejected(dealId, ErrorCode.DEAL_NOT_ACTIVE, "거래가 없습니다", 0);
        }
        DealStateMachine.DriverAvailability online =
                driverId -> market.drivers().get(driverId) == DriverStatus.ONLINE;

        Result result = deals.apply(deal, command, online, now);
        if (result instanceof Result.Rejected r) {
            return new MarketResult.Rejected(dealId, r.code(), r.message(), r.version());
        }
        Result.Accepted accepted = (Result.Accepted) result;

        Map<String, Deal> nextDeals = new HashMap<>(market.deals());
        Map<String, DriverStatus> nextDrivers = new HashMap<>(market.drivers());
        Map<String, List<DealEvent>> events = new LinkedHashMap<>();
        nextDeals.put(dealId, accepted.deal());
        if (!accepted.events().isEmpty()) events.put(dealId, accepted.events());

        for (DealEvent e : accepted.events()) {
            if (e instanceof DealMatched m) {
                String winner = m.match().driverId();
                nextDrivers.put(winner, DriverStatus.MATCHED);
                // R10: every other live bid of the winner goes, in the same step as the match.
                for (Deal other : market.deals().values()) {
                    if (other.dealId().equals(dealId)) continue;
                    Result.Accepted pulled = deals.forceWithdraw(other, winner, WithdrawReason.DRIVER_MATCHED_ELSEWHERE);
                    if (!pulled.events().isEmpty()) {
                        nextDeals.put(other.dealId(), pulled.deal());
                        events.put(other.dealId(), pulled.events());
                    }
                }
            }
        }
        return new MarketResult.Accepted(new MarketState(nextDeals, nextDrivers), events);
    }
}
