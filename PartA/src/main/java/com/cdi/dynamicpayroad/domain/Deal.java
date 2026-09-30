package com.cdi.dynamicpayroad.domain;

import com.cdi.dynamicpayroad.domain.Enums.EndReason;
import com.cdi.dynamicpayroad.domain.Enums.MatchPath;
import com.cdi.dynamicpayroad.domain.Enums.PendingSide;

import java.time.Instant;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.OptionalDouble;

/**
 * Immutable snapshot of one deal. The state machine never mutates a Deal; it returns a new one.
 *
 * @param bids            live bids, at most one per driver (R5)
 * @param lastBidByDriver each driver's most recent bid price, kept after a withdrawal so R1
 *                        cannot be reset by withdrawing and re-bidding
 * @param offer           the rider's live offer, or null
 * @param lastOfferPrice  the rider's most recent offer price (R1 for the rider), or null
 * @param match           filled once MATCHED
 * @param endReason       filled once EXPIRED or CANCELLED
 */
public record Deal(
        String dealId,
        String riderId,
        double originLat,
        double originLng,
        double basePrice,
        Instant createdAt,
        Instant expiresAt,
        DealStatus status,
        PendingSide pendingSide,
        int round,
        long version,
        List<Bid> bids,
        Map<String, Double> lastBidByDriver,
        RiderOffer offer,
        Double lastOfferPrice,
        int withdrawCount,
        int nextBidSeq,
        Match match,
        EndReason endReason) {

    public Deal {
        bids = List.copyOf(bids);
        lastBidByDriver = Map.copyOf(lastBidByDriver);
    }

    /** A freshly created deal: OPEN, version 1, waiting for drivers (R4). */
    public static Deal open(String dealId, String riderId, double originLat, double originLng,
                            double basePrice, Instant now, DealRules rules) {
        return new Deal(dealId, riderId, originLat, originLng, basePrice, now, now.plus(rules.dealTtl()),
                DealStatus.OPEN, PendingSide.DRIVER, 0, 1, List.of(), Map.of(), null, null, 0, 1, null, null);
    }

    /** Live bids, cheapest first (the default order of api-spec §4.2). */
    public List<Bid> bidsAscending() {
        return bids.stream().sorted(Comparator.comparingDouble(Bid::price)).toList();
    }

    public OptionalDouble lowestBidPrice() {
        return bids.stream().mapToDouble(Bid::price).min();
    }

    /** A driver's live bid. Pickup distance and ETA are computed by the server (§6.2). */
    public record Bid(String bidId, String driverId, double price, double driverLat, double driverLng,
                      double pickupDistanceKm, double pickupEtaMin, Instant createdAt) {}

    /** The rider's live counter-offer; it lapses after the offer TTL (R6). */
    public record RiderOffer(double price, Instant createdAt, Instant expiresAt) {}

    /** What DealHistory records when a deal closes (§6.4). */
    public record Match(String driverId, double finalPrice, MatchPath matchPath, int chosenRank,
                        Double lowestBidPrice, double pickupDistanceKm, double pickupEtaMin,
                        Double lowestBidPickupDistanceKm, Double lowestBidPickupEtaMin, Instant matchedAt) {}
}
