package com.cdi.dynamicpayroad.experiment.bots;

import com.cdi.dynamicpayroad.experiment.ActionLog;
import com.cdi.dynamicpayroad.experiment.ActionLog.Action;
import com.cdi.dynamicpayroad.experiment.DealSource;
import com.cdi.dynamicpayroad.experiment.DealSource.DealRow;
import com.cdi.dynamicpayroad.experiment.EpisodeEngine;
import com.cdi.dynamicpayroad.experiment.ExperimentRunner;
import com.cdi.dynamicpayroad.redis.RedisTestSupport;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.SplittableRandom;
import java.util.function.Function;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/** Driver bots on a real Redis (DB 15): one e2 run (C1, seed 1) through the runner's episode loop. */
class DriverBotTest extends RedisTestSupport {

    static final BotParams PARAMS = BotParams.read(BotParams.DEFAULT_PATH);
    static final DealSource DEALS = DealSource.read(DealSource.DEFAULT_PATH);
    static final DealRow ROW = new DealRow("S-T", 10.0, 12.97, 77.59, 180.0, 1.1, 198.0, true);

    @Test
    void e2RunNeverBreaksR1OrTheBandAndTheLowestBidderNeverConcedes() {
        List<DriverBot> pool = DriverBot.pool(PARAMS, "C1", 1);
        RiderBot rider = new RiderBot();
        List<DealRow> order = DEALS.shuffled(1);
        List<String> badRejects = new ArrayList<>();
        List<String> lowestConceded = new ArrayList<>();
        int updates = 0;
        ActionLog log = new ActionLog("e2-C1-s1");
        for (int i = 0; i < PARAMS.dealsPerRun(); i++) {
            ExperimentRunner.episode(market, PARAMS, pool, rider, order.get(i % order.size()), 1, i,
                    PARAMS.defaultN(), false, null, log);

            Map<String, Double> live = new HashMap<>();
            for (ActionLog.Row a : log.rows()) {
                if (a.rejectCode() != null && (a.rejectCode().equals("PRICE_NOT_CONCEDED")
                        || a.rejectCode().equals("OUT_OF_BAND"))) {
                    badRejects.add(a.toString());
                }
                if (a.action() == Action.BID_UPDATE) {
                    updates++;
                    double mine = live.get(a.driverId());
                    boolean lowest = live.entrySet().stream()
                            .noneMatch(e -> !e.getKey().equals(a.driverId()) && e.getValue() < mine);
                    if (lowest) lowestConceded.add(a.toString());
                }
                if ((a.action() == Action.BID_PLACE || a.action() == Action.BID_UPDATE) && a.accepted()) {
                    live.put(a.driverId(), a.price());
                }
            }
            log.clear();
        }
        assertThat(updates).as("drivers conceded at all").isGreaterThan(100);
        assertThat(badRejects).isEmpty();
        assertThat(lowestConceded).isEmpty();
    }

    @Test
    void poolDealsStrategiesByConfigShares() {
        Function<String, Map<DriverStrategy, Long>> count = c -> DriverBot.pool(PARAMS, c, 5).stream()
                .collect(Collectors.groupingBy(DriverBot::driverStrategy, Collectors.counting()));
        assertThat(count.apply("C1")).containsExactlyInAnyOrderEntriesOf(Map.of(
                DriverStrategy.AGG, 15L, DriverStrategy.CON, 15L, DriverStrategy.DIST, 15L, DriverStrategy.OPP, 15L));
        assertThat(count.apply("C2")).containsExactlyInAnyOrderEntriesOf(Map.of(
                DriverStrategy.AGG, 33L, DriverStrategy.CON, 9L, DriverStrategy.DIST, 9L, DriverStrategy.OPP, 9L));
        assertThat(count.apply("C4")).containsEntry(DriverStrategy.OPP, 33L);

        List<DriverBot> a = DriverBot.pool(PARAMS, "C1", 5), b = DriverBot.pool(PARAMS, "C1", 5),
                c = DriverBot.pool(PARAMS, "C1", 6);
        assertThat(a.get(0).id()).isEqualTo("D-0001");
        assertThat(a.stream().map(DriverBot::strategy).toList()).isEqualTo(b.stream().map(DriverBot::strategy).toList())
                .isNotEqualTo(c.stream().map(DriverBot::strategy).toList());
    }

    @Test
    void preparedValuesFollowTheStrategyTable() {
        for (DriverStrategy s : DriverStrategy.values()) {
            DriverBot d = new DriverBot("D-1", s);
            SplittableRandom rng = new SplittableRandom(3);
            for (int k = 0; k < 200; k++) {
                d.prepare(PARAMS, ROW, 0.7, 3.0, false, rng);
                // Cost uses base_dry: at most 180 × 0.95 × (1 + 0.02 × 5) = 188.1, so the floor is under base_price.
                assertThat(d.floor()).isBetween(0.7 * 198.0, 188.1);
                assertThat(d.margin()).isBetween(0.0, 0.05);
                double first = d.firstBid();
                assertThat(first).isBetween(d.floor(), 3.0 * 198.0);
                double[] at = d.position().orElseThrow();
                double km = Math.hypot((at[0] - ROW.originLat()) * 111.0,
                        (at[1] - ROW.originLng()) * 111.0 * Math.cos(Math.toRadians(ROW.originLat())));
                assertThat(km).isBetween(0.3 - 1e-9, 5.0 + 1e-9);
                if (s == DriverStrategy.AGG) assertThat(first).isBetween(1.30 * 198.0, 2.00 * 198.0);
                if (s == DriverStrategy.CON) assertThat(first).isBetween(Math.max(1.05 * 198.0, d.floor()), 1.20 * 198.0);
                if (s == DriverStrategy.OPP) assertThat(first).isEqualTo(1.50 * 198.0); // nobody bid yet
            }
        }
    }

    @Test
    void sameSeedAndDealIndexGiveTheSameEpisode() {
        List<DriverBot> pool = DriverBot.pool(PARAMS, "C3", 2);
        RiderBot rider = new RiderBot();
        ActionLog a = new ActionLog("x"), b = new ActionLog("x");
        EpisodeEngine.Result r1 = ExperimentRunner.episode(market, PARAMS, pool, rider, ROW, 2, 7, 5, false, null, a);
        EpisodeEngine.Result r2 = ExperimentRunner.episode(market, PARAMS, pool, rider, ROW, 2, 7, 5, false, null, b);
        assertThat(b.rows()).isEqualTo(a.rows());
        assertThat(r2.deal().match()).isEqualTo(r1.deal().match());
    }
}
