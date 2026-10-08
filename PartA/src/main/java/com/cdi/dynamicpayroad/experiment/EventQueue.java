package com.cdi.dynamicpayroad.experiment;

import java.time.Instant;
import java.util.Comparator;
import java.util.PriorityQueue;

/**
 * Single-threaded discrete-event queue (plan v6 §3.3). Events run in (time, insertion order);
 * the clock jumps to each event's time just before it runs.
 */
public final class EventQueue {

    private record Entry(Instant at, long seq, Runnable action) {}

    private final VirtualClock clock;
    private final PriorityQueue<Entry> queue = new PriorityQueue<>(
            Comparator.comparing(Entry::at).thenComparingLong(Entry::seq));
    private long nextSeq;

    public EventQueue(VirtualClock clock) {
        this.clock = clock;
    }

    public VirtualClock clock() {
        return clock;
    }

    /** Runs {@code action} at {@code at}. Times before the clock are refused. */
    public void schedule(Instant at, Runnable action) {
        if (at.isBefore(clock.instant())) {
            throw new IllegalArgumentException("cannot schedule in the past: " + at + " < " + clock.instant());
        }
        queue.add(new Entry(at, nextSeq++, action));
    }

    /** Runs every event at or before {@code end}, in order, including ones scheduled while running. */
    public void runUntil(Instant end) {
        while (!queue.isEmpty() && !queue.peek().at().isAfter(end)) {
            Entry e = queue.poll();
            clock.advanceTo(e.at());
            e.action().run();
        }
    }

    /** Drops every pending event (the deal ended). */
    public void clear() {
        queue.clear();
    }

    public boolean isEmpty() {
        return queue.isEmpty();
    }

    public int size() {
        return queue.size();
    }
}
