package com.cdi.dynamicpayroad.deal;

import com.cdi.dynamicpayroad.model.Location;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** One bargaining session (api-spec §3). All state changes go through DealService under the deal's lock. */
public class Deal {

    public enum Status { OPEN, NEGOTIATING, MATCHED, EXPIRED, CANCELLED }

    /** A driver's live bid. One per driver; a new bid replaces the old one (R5). */
    public record Bid(String bidId, String driverId, double price,
                      double driverLat, double driverLng,
                      double pickupDistanceKm, double pickupEtaMin, Instant createdAt) {}

    final String dealId;
    final String riderId;
    final Location origin;
    final Location dest;
    final double basePrice;
    final double distanceKm;
    final double durationMin;
    final Instant createdAt;
    final Instant expiresAt;

    Status status = Status.OPEN;
    String pendingSide = "DRIVER";
    int round = 0;
    long version = 1;
    int nextBidSeq = 1;
    final Map<String, Bid> bidsByDriver = new LinkedHashMap<>();

    // Filled when the deal matches.
    Bid winningBid;
    String matchPath;
    int chosenRank;
    Instant matchedAt;

    Deal(String dealId, String riderId, Location origin, Location dest,
         double basePrice, double distanceKm, double durationMin,
         Instant createdAt, Instant expiresAt) {
        this.dealId = dealId;
        this.riderId = riderId;
        this.origin = origin;
        this.dest = dest;
        this.basePrice = basePrice;
        this.distanceKm = distanceKm;
        this.durationMin = durationMin;
        this.createdAt = createdAt;
        this.expiresAt = expiresAt;
    }

    /** Bids by price, cheapest first. */
    List<Bid> bidsAscending() {
        List<Bid> bids = new ArrayList<>(bidsByDriver.values());
        bids.sort(Comparator.comparingDouble(Bid::price));
        return bids;
    }

    /** Cheapest live bid price, or null when there are no bids. */
    Double lowestBidPrice() {
        return bidsByDriver.values().stream()
                .map(Bid::price)
                .min(Comparator.naturalOrder())
                .orElse(null);
    }
}
