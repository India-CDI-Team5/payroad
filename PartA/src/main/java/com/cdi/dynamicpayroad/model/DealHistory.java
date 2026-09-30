package com.cdi.dynamicpayroad.model;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.Instant;

/** One closed deal: who matched, the market at that moment, and how the price was reached. */
@Entity
@Table(name = "deal_history")
public class DealHistory {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String userId;
    private String driverId;
    private Instant matchedAt;

    // Local market snapshot at match time (within the 5km radius).
    private double pickupDistanceKm;
    private int demandInRadius;
    private int supplyInRadius;

    // Price: markupRatio = finalPrice / basePrice.
    private double basePrice;
    private double finalPrice;
    private double markupRatio;

    // Negotiation trace (api-spec §6.4).
    private int roundCount;
    private int bidderCount;
    private long negotiationDurationMs;

    // Reproducibility: which experiment arm produced this row, and the RNG seed behind it.
    private String experimentTag;
    private Long randomSeed;

    protected DealHistory() {}

    public DealHistory(String userId, String driverId, Instant matchedAt,
                       double pickupDistanceKm, int demandInRadius, int supplyInRadius,
                       double basePrice, double finalPrice, double markupRatio,
                       int roundCount, int bidderCount, long negotiationDurationMs,
                       String experimentTag, Long randomSeed) {
        this.userId = userId;
        this.driverId = driverId;
        this.matchedAt = matchedAt;
        this.pickupDistanceKm = pickupDistanceKm;
        this.demandInRadius = demandInRadius;
        this.supplyInRadius = supplyInRadius;
        this.basePrice = basePrice;
        this.finalPrice = finalPrice;
        this.markupRatio = markupRatio;
        this.roundCount = roundCount;
        this.bidderCount = bidderCount;
        this.negotiationDurationMs = negotiationDurationMs;
        this.experimentTag = experimentTag;
        this.randomSeed = randomSeed;
    }

    public Long getId() { return id; }
    public String getUserId() { return userId; }
    public String getDriverId() { return driverId; }
    public Instant getMatchedAt() { return matchedAt; }
    public double getPickupDistanceKm() { return pickupDistanceKm; }
    public int getDemandInRadius() { return demandInRadius; }
    public int getSupplyInRadius() { return supplyInRadius; }
    public double getBasePrice() { return basePrice; }
    public double getFinalPrice() { return finalPrice; }
    public double getMarkupRatio() { return markupRatio; }
    public int getRoundCount() { return roundCount; }
    public int getBidderCount() { return bidderCount; }
    public long getNegotiationDurationMs() { return negotiationDurationMs; }
    public String getExperimentTag() { return experimentTag; }
    public Long getRandomSeed() { return randomSeed; }
}
