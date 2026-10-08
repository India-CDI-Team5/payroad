package com.cdi.dynamicpayroad.domain;

import java.time.Duration;

/**
 * Protocol parameters (api-spec §2, §6.2). Kept in one record so the experiment runner can
 * sweep them (E4) without touching the rules. create_deal.lua copies them into each deal.
 */
public record DealRules(
        double bandMinRatio,
        double bandMaxRatio,
        Duration dealTtl,
        Duration offerTtl,
        int roundLimit,
        double avgSpeedKmh,
        double detourFactor,
        int maxActiveBids,
        Duration presenceTtl) {

    /** The values frozen in api-spec v1.3. */
    public static DealRules defaults() {
        return new DealRules(0.7, 3.0, Duration.ofSeconds(180), Duration.ofSeconds(30), 20, 20.0, 1.3,
                50, Duration.ofSeconds(60));
    }

    public PriceBand band(double basePrice) {
        return new PriceBand(basePrice * bandMinRatio, basePrice * bandMaxRatio);
    }

    /** §6.2: pickupEtaMin = distance / speed x 60 x detour. */
    public double pickupEtaMin(double pickupDistanceKm) {
        return pickupDistanceKm / avgSpeedKmh * 60 * detourFactor;
    }

    public record PriceBand(double min, double max) {
        public boolean contains(double price) {
            return price >= min && price <= max;
        }
    }
}
