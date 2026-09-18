package com.zerowaiting.dynamicpayroad.model;

import jakarta.persistence.Embeddable;

/**
 * Real-world position (latitude/longitude in degrees). Distance is the
 * great-circle (haversine) distance in kilometres, so the 5km matching
 * radius means an actual 5km on the ground.
 */
@Embeddable
public class Location {
    private static final double EARTH_RADIUS_KM = 6371.0;

    private double lat;
    private double lon;

    protected Location() {}

    public Location(double lat, double lon) {
        this.lat = lat;
        this.lon = lon;
    }

    /** Great-circle distance to another location, in kilometres. */
    public double distanceTo(Location other) {
        double dLat = Math.toRadians(other.lat - this.lat);
        double dLon = Math.toRadians(other.lon - this.lon);
        double a = Math.sin(dLat / 2) * Math.sin(dLat / 2)
                + Math.cos(Math.toRadians(this.lat)) * Math.cos(Math.toRadians(other.lat))
                * Math.sin(dLon / 2) * Math.sin(dLon / 2);
        double c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        return EARTH_RADIUS_KM * c;
    }

    public double getLat() { return lat; }
    public double getLon() { return lon; }
}
