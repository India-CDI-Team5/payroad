package com.cdi.dynamicpayroad.engine;

import com.cdi.dynamicpayroad.model.Driver;
import com.cdi.dynamicpayroad.model.Location;
import com.cdi.dynamicpayroad.model.User;
import org.springframework.stereotype.Component;

import java.util.Collection;

/**
 * process1: given a requesting user, look only within a 5km radius. The best
 * driver is the nearest waiting one in range; the price multiplier comes from
 * the local demand/supply balance (online users vs. waiting drivers within the
 * same radius). Demand-heavy areas price up (surge), supply-heavy areas price
 * down (discount), with 1.0 = balanced.
 */
@Component
public class MatchingEngine {
    private static final double RADIUS_KM = 5.0;

    /**
     * Price multiplier is clamped to this band so fares stay sane at extremes.
     * Floor is below 1.0 so an oversupplied area actually discounts the fare;
     * ceiling caps how far a supply crunch can surge it.
     */
    private static final double MIN_SURGE = 0.7;
    private static final double MAX_SURGE = 3.0;

    /**
     * Outcome of one match attempt. {@code driver} is null when no waiting
     * driver sits within the radius; the demand/supply/surge fields are still
     * populated so callers can log the local market state either way.
     */
    public record Outcome(Driver driver, double pickupDistanceKm,
                          int demandInRadius, int supplyInRadius, double surge) {
        public boolean matched() { return driver != null; }
    }

    public Outcome evaluate(User user, Collection<User> onlineUsers, Collection<Driver> waitingDrivers) {
        return evaluateAt(user.getLocation(), onlineUsers, waitingDrivers);
    }

    /** Same local demand/supply/surge computation, but around an arbitrary point rather than a requesting user. */
    public Outcome evaluateAt(Location origin, Collection<User> onlineUsers, Collection<Driver> waitingDrivers) {
        // Demand = online users within radius (the requester counts too).
        int demand = 0;
        for (User u : onlineUsers) {
            if (origin.distanceTo(u.getLocation()) <= RADIUS_KM) demand++;
        }

        // Supply = waiting drivers within radius; track the nearest as the pick.
        int supply = 0;
        Driver best = null;
        double bestDist = Double.MAX_VALUE;
        for (Driver d : waitingDrivers) {
            double dist = origin.distanceTo(d.getLocation());
            if (dist <= RADIUS_KM) {
                supply++;
                if (dist < bestDist) {
                    best = d;
                    bestDist = dist;
                }
            }
        }

        double surge = surge(demand, supply);
        double pickupDist = best == null ? 0.0 : bestDist;
        return new Outcome(best, pickupDist, demand, supply, surge);
    }

    /**
     * More riders than nearby drivers pushes price up (>1.0); more drivers than
     * riders pulls it down (<1.0). demand==supply is the neutral 1.0 point.
     * Rounded to 0.1 steps like real surge tiers.
     */
    private double surge(int demand, int supply) {
        if (supply == 0) return MAX_SURGE;
        double ratio = (double) demand / supply;
        double clamped = Math.max(MIN_SURGE, Math.min(MAX_SURGE, ratio));
        return Math.round(clamped * 10.0) / 10.0;
    }
}
