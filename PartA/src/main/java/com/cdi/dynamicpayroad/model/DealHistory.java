package com.cdi.dynamicpayroad.model;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import com.cdi.dynamicpayroad.domain.Deal;

import java.time.Duration;
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

    // Mechanism analysis (api-spec §6.4). Boxed so the columns are nullable: rows written
    // before these columns existed, and deals that closed without a match, leave them empty.
    private String dealId;
    private String endStatus;                 // MATCHED | EXPIRED | CANCELLED
    private String endReason;                 // TTL | ROUND_LIMIT | CANCELLED_BY_RIDER | RIDER_DISCONNECTED
    private String matchPath;                 // RIDER_PICKED_BID | DRIVER_TOOK_OFFER
    private Integer chosenRank;               // 1 = cheapest bid; 0 = driver took the rider's offer
    private Double lowestBidPrice;
    private Double winningPickupDistanceKm;
    private Double winningPickupEtaMin;
    private Double lowestBidPickupDistanceKm;
    private Double lowestBidPickupEtaMin;
    private Integer withdrawCount;
    private Instant createdAt;

    protected DealHistory() {}

    /**
     * One row for a deal that has just closed (matched, expired or cancelled).
     * Unmatched deals keep finalPrice, markupRatio and pickupDistanceKm at 0 because those
     * legacy columns are NOT NULL; filter on endStatus = MATCHED before averaging them.
     *
     * @param demand      riders within 5 km when the deal was created
     * @param supply      waiting drivers within 5 km when the deal was created
     * @param bidderCount distinct drivers who bid at any point, withdrawn ones included
     */
    public static DealHistory closed(Deal deal, int demand, int supply, int bidderCount,
                                     String experimentTag, Long randomSeed, Instant closedAt) {
        Deal.Match m = deal.match();
        DealHistory h = new DealHistory();
        h.dealId = deal.dealId();
        h.userId = deal.riderId();
        h.createdAt = deal.createdAt();
        h.demandInRadius = demand;
        h.supplyInRadius = supply;
        h.basePrice = deal.basePrice();
        h.roundCount = deal.round();
        h.bidderCount = bidderCount;
        h.withdrawCount = deal.withdrawCount();
        h.negotiationDurationMs = Duration.between(deal.createdAt(), closedAt).toMillis();
        h.endStatus = deal.status().name();
        h.endReason = deal.endReason() == null ? null : deal.endReason().name();
        h.experimentTag = experimentTag;
        h.randomSeed = randomSeed;
        if (m != null) {
            h.driverId = m.driverId();
            h.matchedAt = m.matchedAt();
            h.finalPrice = m.finalPrice();
            h.markupRatio = m.finalPrice() / deal.basePrice();
            h.matchPath = m.matchPath().name();
            h.chosenRank = m.chosenRank();
            h.lowestBidPrice = m.lowestBidPrice();
            h.winningPickupDistanceKm = m.pickupDistanceKm();
            h.winningPickupEtaMin = m.pickupEtaMin();
            h.lowestBidPickupDistanceKm = m.lowestBidPickupDistanceKm();
            h.lowestBidPickupEtaMin = m.lowestBidPickupEtaMin();
            h.pickupDistanceKm = m.pickupDistanceKm() == null ? 0 : m.pickupDistanceKm();
        }
        return h;
    }

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
    public String getDealId() { return dealId; }
    public String getEndStatus() { return endStatus; }
    public String getEndReason() { return endReason; }
    public String getMatchPath() { return matchPath; }
    public Integer getChosenRank() { return chosenRank; }
    public Double getLowestBidPrice() { return lowestBidPrice; }
    public Double getWinningPickupDistanceKm() { return winningPickupDistanceKm; }
    public Double getWinningPickupEtaMin() { return winningPickupEtaMin; }
    public Double getLowestBidPickupDistanceKm() { return lowestBidPickupDistanceKm; }
    public Double getLowestBidPickupEtaMin() { return lowestBidPickupEtaMin; }
    public Integer getWithdrawCount() { return withdrawCount; }
    public Instant getCreatedAt() { return createdAt; }
}
