package com.cdi.dynamicpayroad.experiment;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;

/**
 * The experiment runner's clock (plan v6 §3.3). It stands still until the event queue moves it
 * to the next event's time, and it never goes back. Always UTC.
 */
public final class VirtualClock extends Clock {

    /** Every episode starts here, so the same seed gives the same epoch-ms arguments to Lua. */
    public static final Instant START = Instant.parse("2026-01-01T00:00:00Z");

    private Instant now;

    public VirtualClock() {
        this(START);
    }

    public VirtualClock(Instant start) {
        this.now = start;
    }

    @Override
    public Instant instant() {
        return now;
    }

    /** Moves the clock forward to {@code t}; staying put is allowed, going back is not. */
    public void advanceTo(Instant t) {
        if (t.isBefore(now)) throw new IllegalArgumentException("clock cannot go back: " + now + " -> " + t);
        now = t;
    }

    @Override
    public ZoneId getZone() {
        return ZoneOffset.UTC;
    }

    @Override
    public Clock withZone(ZoneId zone) {
        if (ZoneOffset.UTC.equals(zone.normalized())) return this;
        throw new UnsupportedOperationException("VirtualClock is UTC only");
    }
}
