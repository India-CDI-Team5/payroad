package com.cdi.dynamicpayroad.model;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.Instant;

@Entity
@Table(name = "match_result")
public class MatchResult {
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
    private double surge;

    // Fare = baseFare * surge.
    private double baseFare;
    private double finalFare;

    protected MatchResult() {}

    public MatchResult(String userId, String driverId, Instant matchedAt,
                       double pickupDistanceKm, int demandInRadius, int supplyInRadius,
                       double surge, double baseFare, double finalFare) {
        this.userId = userId;
        this.driverId = driverId;
        this.matchedAt = matchedAt;
        this.pickupDistanceKm = pickupDistanceKm;
        this.demandInRadius = demandInRadius;
        this.supplyInRadius = supplyInRadius;
        this.surge = surge;
        this.baseFare = baseFare;
        this.finalFare = finalFare;
    }

    public Long getId() { return id; }
    public String getUserId() { return userId; }
    public String getDriverId() { return driverId; }
    public Instant getMatchedAt() { return matchedAt; }
    public double getPickupDistanceKm() { return pickupDistanceKm; }
    public int getDemandInRadius() { return demandInRadius; }
    public int getSupplyInRadius() { return supplyInRadius; }
    public double getSurge() { return surge; }
    public double getBaseFare() { return baseFare; }
    public double getFinalFare() { return finalFare; }
}
