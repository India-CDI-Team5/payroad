package com.cdi.dynamicpayroad.domain;

/** Small closed vocabularies used in deals and events (api-spec §5.3, §6.4). */
public final class Enums {
    private Enums() {}

    /** Who the UI shows as "expected to respond next" (R4). Never restricts who may act. */
    public enum PendingSide { RIDER, DRIVER }

    /** How a deal was closed (§1.4): rider picked a bid, or a driver took the rider's offer. */
    public enum MatchPath { RIDER_PICKED_BID, DRIVER_TOOK_OFFER }

    /** Why a deal ended without a match (§5.3 {@code deal.expired}). */
    public enum EndReason { TTL, ROUND_LIMIT, CANCELLED_BY_RIDER, RIDER_DISCONNECTED }

    /** Why a bid left the book (§5.3 {@code bid.withdrawn}). */
    public enum WithdrawReason { BY_DRIVER, DRIVER_DISCONNECTED, DRIVER_MATCHED_ELSEWHERE }

    /** Driver presence as the market sees it (R11). Absent from the market = offline. */
    public enum DriverStatus { ONLINE, MATCHED }
}
