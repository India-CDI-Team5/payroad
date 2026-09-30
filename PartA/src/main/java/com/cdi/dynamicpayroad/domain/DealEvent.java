package com.cdi.dynamicpayroad.domain;

import com.cdi.dynamicpayroad.domain.Enums.EndReason;
import com.cdi.dynamicpayroad.domain.Enums.PendingSide;
import com.cdi.dynamicpayroad.domain.Enums.WithdrawReason;

import java.time.Instant;

/**
 * Server-to-client events on /topic/deal/{dealId} (api-spec §5.3). Every event carries the
 * deal's version after the change (§5.6). Wire names are given by {@link #name()}.
 */
public sealed interface DealEvent {

    String dealId();

    long version();

    /** The event name clients switch on, e.g. {@code bid.placed}. */
    String name();

    record BidPlaced(String dealId, Deal.Bid bid, Double lowestBidPrice, int bidderCount,
                     PendingSide pendingSide, int round, long version) implements DealEvent {
        public String name() { return "bid.placed"; }
    }

    record BidUpdated(String dealId, Deal.Bid bid, Double lowestBidPrice, int bidderCount,
                      PendingSide pendingSide, int round, long version) implements DealEvent {
        public String name() { return "bid.updated"; }
    }

    record BidWithdrawn(String dealId, String bidId, String driverId, WithdrawReason reason,
                        Double lowestBidPrice, int bidderCount, int round, long version) implements DealEvent {
        public String name() { return "bid.withdrawn"; }
    }

    record OfferPosted(String dealId, double price, Instant expiresAt, PendingSide pendingSide,
                       int round, long version) implements DealEvent {
        public String name() { return "offer.posted"; }
    }

    record OfferExpired(String dealId, PendingSide pendingSide, int round, long version) implements DealEvent {
        public String name() { return "offer.expired"; }
    }

    record DealMatched(String dealId, Deal.Match match, long version) implements DealEvent {
        public String name() { return "deal.matched"; }
    }

    record DealExpired(String dealId, EndReason reason, long version) implements DealEvent {
        public String name() { return "deal.expired"; }
    }
}
