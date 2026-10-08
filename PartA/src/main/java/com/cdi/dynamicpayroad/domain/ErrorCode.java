package com.cdi.dynamicpayroad.domain;

/** The 13 rejection codes of api-spec §5.5, sent to the requester in an {@code error} event. */
public enum ErrorCode {
    /** R1: a driver raised, or the rider lowered, their own previous price. */
    PRICE_NOT_CONCEDED,
    /** R2: price outside basePrice x [0.7, 3.0]. */
    OUT_OF_BAND,
    /** R9: another accept already closed the deal. */
    DEAL_ALREADY_MATCHED,
    /** The deal is EXPIRED or CANCELLED. */
    DEAL_NOT_ACTIVE,
    /** The chosen bidId does not exist or was withdrawn. */
    BID_NOT_FOUND,
    /** A driver tried to take an offer the rider never posted. */
    OFFER_NOT_FOUND,
    /** R6: the rider's offer passed its 30 s TTL. */
    OFFER_EXPIRED,
    /** R11: the driver is MATCHED elsewhere or not present. */
    DRIVER_NOT_AVAILABLE,
    /** R11: a rider acted on someone else's deal. */
    NOT_DEAL_OWNER,
    /** The client's version is stale; it must resync with GET /api/deals/{id}. */
    VERSION_CONFLICT,
    /** R8: this action would exceed 20 rounds. */
    ROUND_LIMIT_EXCEEDED,
    /** R13: 기사당 동시 활성 호가 50건 초과 */
    MAX_ACTIVE_BIDS_EXCEEDED,
    /** More than 10 driver actions per minute. Out of scope for now (plan v4 §7). */
    RATE_LIMIT_EXCEEDED
}
