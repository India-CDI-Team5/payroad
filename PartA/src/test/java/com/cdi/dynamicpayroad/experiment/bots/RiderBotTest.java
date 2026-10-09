package com.cdi.dynamicpayroad.experiment.bots;

import com.cdi.dynamicpayroad.domain.Deal;
import com.cdi.dynamicpayroad.domain.DealStatus;
import com.cdi.dynamicpayroad.domain.Enums.EndReason;
import com.cdi.dynamicpayroad.domain.Enums.MatchPath;
import com.cdi.dynamicpayroad.experiment.ActionLog;
import com.cdi.dynamicpayroad.experiment.ActionLog.Action;
import com.cdi.dynamicpayroad.experiment.DealSource;
import com.cdi.dynamicpayroad.experiment.DealSource.DealRow;
import com.cdi.dynamicpayroad.experiment.EpisodeEngine;
import com.cdi.dynamicpayroad.experiment.ExperimentRunner;
import com.cdi.dynamicpayroad.redis.RedisTestSupport;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.SplittableRandom;

import static org.assertj.core.api.Assertions.assertThat;

/** The rider bot on a real Redis (DB 15), through the runner's episode loop. */
class RiderBotTest extends RedisTestSupport {

    static final BotParams PARAMS = BotParams.read(BotParams.DEFAULT_PATH);
    static final DealSource DEALS = DealSource.read(DealSource.DEFAULT_PATH);
    static final DealRow ROW = new DealRow("S-T", 10.0, 12.97, 77.59, 180.0, 1.1, 198.0, true);

    @Test
    void offersOnlyRiseAndNoBidOverBudgetIsAccepted() {
        RiderBot rider = new RiderBot();
        List<String> falling = new ArrayList<>();
        List<String> overBudget = new ArrayList<>();
        int offers = 0, picked = 0;
        for (String config : List.of("C1", "C2")) {
            List<DriverBot> pool = DriverBot.pool(PARAMS, config, 1);
            List<DealRow> order = DEALS.shuffled(1);
            ActionLog log = new ActionLog(config);
            for (int i = 0; i < 150; i++) {
                EpisodeEngine.Result r = ExperimentRunner.episode(market, PARAMS, pool, rider,
                        order.get(i % order.size()), 1, i, PARAMS.defaultN(), false, null, log);

                Double last = null;
                for (ActionLog.Row a : log.rows()) {
                    if (a.action() != Action.OFFER_POST) continue;
                    offers++;
                    if (last != null && a.price() <= last) falling.add(a.toString());
                    last = a.price();
                }
                Deal.Match m = r.deal().match();
                if (m != null && m.matchPath() == MatchPath.RIDER_PICKED_BID) {
                    picked++;
                    if (m.finalPrice() > rider.budget()) overBudget.add(r.row().dealId() + " " + m.finalPrice());
                }
                log.clear();
            }
        }
        assertThat(offers).isGreaterThan(50);
        assertThat(picked).isGreaterThan(20);
        assertThat(falling).isEmpty();
        assertThat(overBudget).isEmpty();
    }

    @Test
    void preparedValuesStayInTheirRangesAndTauCanBeFixed() {
        RiderBot rider = new RiderBot();
        SplittableRandom rng = new SplittableRandom(9);
        for (int k = 0; k < 200; k++) {
            rider.prepare(PARAMS, ROW, false, null, rng);
            assertThat(rider.budget()).isBetween(0.9 * 198.0, 1.6 * 198.0);
            assertThat(rider.tau()).isBetween(0.0, 0.05);
        }
        rider.prepare(PARAMS, ROW, false, 0.02, new SplittableRandom(1));
        double budget = rider.budget();
        assertThat(rider.tau()).isEqualTo(0.02);
        rider.prepare(PARAMS, ROW, false, null, new SplittableRandom(1));
        assertThat(rider.budget()).as("fixing τ leaves the other draws alone").isEqualTo(budget);
    }

    @Test
    void fixedPriceRiderOffersBasePriceOnceAndCancelsWhenItLapses() {
        RiderBot rider = new RiderBot();
        List<DriverBot> pool = DriverBot.pool(PARAMS, "C1", 1);
        int matched = 0, cancelled = 0;
        ActionLog log = new ActionLog("e3");
        List<DealRow> order = DEALS.shuffled(4);
        for (int i = 0; i < 60; i++) {
            DealRow row = order.get(i);
            EpisodeEngine.Result r = ExperimentRunner.episode(market, PARAMS, pool, rider, row, 4, i, 5, true, null, log);
            assertThat(log.rows().stream().filter(a -> a.action() == Action.OFFER_POST).map(ActionLog.Row::price))
                    .containsExactly(row.basePrice());
            assertThat(log.rows()).noneMatch(a -> a.action() == Action.BID_PLACE || a.action() == Action.BID_UPDATE);
            if (r.deal().status() == DealStatus.MATCHED) {
                matched++;
                assertThat(r.deal().match().finalPrice()).isEqualTo(row.basePrice());
                assertThat(r.deal().match().matchPath()).isEqualTo(MatchPath.DRIVER_TOOK_OFFER);
            } else {
                cancelled++;
                assertThat(r.deal().endReason()).isEqualTo(EndReason.CANCELLED_BY_RIDER);
                assertThat(r.durationSec()).isEqualTo(30.0);
            }
            log.clear();
        }
        assertThat(matched).isPositive();
    }
}
