package com.cdi.dynamicpayroad.domain;

/**
 * Everything that can happen to a deal. The first five mirror the STOMP messages of
 * api-spec §5.2; {@code version} is the client's last known version (null = skip the CAS check).
 */
public sealed interface DealCommand {

    /** /app/deal/{id}/bid: place or replace this driver's bid (R1, R2, R5, R11). */
    record PlaceBid(String driverId, double price, double driverLat, double driverLng, Long version) implements DealCommand {}

    /** /app/deal/{id}/bid/withdraw (R5). Does not count as a round (R8). */
    record WithdrawBid(String driverId, Long version) implements DealCommand {}

    /** /app/deal/{id}/offer: the rider posts or raises a counter-offer (R1, R2, R11). */
    record PostOffer(String riderId, double price, Long version) implements DealCommand {}

    /** /app/deal/{id}/accept-bid: the rider picks a specific bid (R3, R9). */
    record AcceptBid(String riderId, String bidId, Long version) implements DealCommand {}

    /** /app/deal/{id}/accept-offer: the first driver to take the rider's offer wins (R3, R6, R9, R11). */
    record AcceptOffer(String driverId, Long version) implements DealCommand {}

    /** DELETE /api/deals/{id} (R12). */
    record Cancel(String riderId) implements DealCommand {}

    /** Periodic check for offer TTL (R6) and deal TTL (R7). Carries no data: the time is the apply() argument. */
    record Tick() implements DealCommand {}
}
