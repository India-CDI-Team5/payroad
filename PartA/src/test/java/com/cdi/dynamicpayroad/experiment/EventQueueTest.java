package com.cdi.dynamicpayroad.experiment;

import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class EventQueueTest {

    static final Instant T0 = VirtualClock.START;

    @Test
    void runsByTimeThenInsertionOrderAndMovesTheClock() {
        VirtualClock clock = new VirtualClock();
        EventQueue q = new EventQueue(clock);
        List<String> seen = new ArrayList<>();
        q.schedule(T0.plusSeconds(5), () -> seen.add("b@" + clock.instant()));
        q.schedule(T0.plusSeconds(1), () -> seen.add("a@" + clock.instant()));
        q.schedule(T0.plusSeconds(5), () -> seen.add("c@" + clock.instant()));

        q.runUntil(T0.plusSeconds(10));

        assertThat(seen).containsExactly("a@" + T0.plusSeconds(1), "b@" + T0.plusSeconds(5), "c@" + T0.plusSeconds(5));
        assertThat(clock.instant()).isEqualTo(T0.plusSeconds(5));
        assertThat(q.isEmpty()).isTrue();
    }

    @Test
    void eventsScheduledWhileRunningRunInOrderAndSameTimeGoesLast() {
        VirtualClock clock = new VirtualClock();
        EventQueue q = new EventQueue(clock);
        List<String> seen = new ArrayList<>();
        q.schedule(T0.plusSeconds(2), () -> {
            seen.add("first");
            q.schedule(clock.instant(), () -> seen.add("same-time"));
            q.schedule(T0.plusSeconds(3), () -> seen.add("later"));
        });
        q.schedule(T0.plusSeconds(2), () -> seen.add("second"));

        q.runUntil(T0.plusSeconds(60));

        assertThat(seen).containsExactly("first", "second", "same-time", "later");
    }

    @Test
    void stopsAtEndAndKeepsLaterEvents() {
        VirtualClock clock = new VirtualClock();
        EventQueue q = new EventQueue(clock);
        List<Integer> seen = new ArrayList<>();
        q.schedule(T0.plusSeconds(10), () -> seen.add(10));
        q.schedule(T0.plusSeconds(20), () -> seen.add(20));

        q.runUntil(T0.plusSeconds(10));
        assertThat(seen).containsExactly(10);
        assertThat(q.size()).isEqualTo(1);

        q.clear();
        q.runUntil(T0.plusSeconds(100));
        assertThat(seen).containsExactly(10);
        assertThat(clock.instant()).isEqualTo(T0.plusSeconds(10));
    }

    @Test
    void neitherClockNorQueueGoesBack() {
        VirtualClock clock = new VirtualClock();
        clock.advanceTo(T0.plusSeconds(5));
        clock.advanceTo(T0.plusSeconds(5));
        assertThatThrownBy(() -> clock.advanceTo(T0.plusSeconds(4))).isInstanceOf(IllegalArgumentException.class);

        EventQueue q = new EventQueue(clock);
        assertThatThrownBy(() -> q.schedule(T0.plusSeconds(4), () -> {})).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void clockIsUtcAndStartsAtTheFixedEpoch() {
        VirtualClock clock = new VirtualClock();
        assertThat(clock.instant()).isEqualTo(Instant.parse("2026-01-01T00:00:00Z"));
        assertThat(clock.getZone().getId()).isEqualTo("Z");
        assertThat(clock.millis()).isEqualTo(clock.instant().toEpochMilli());
    }
}
