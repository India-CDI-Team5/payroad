package com.cdi.dynamicpayroad.experiment.bots;

import com.cdi.dynamicpayroad.experiment.ActionLog;
import com.cdi.dynamicpayroad.experiment.ActionLog.Action;
import com.cdi.dynamicpayroad.experiment.CsvExporter;
import com.cdi.dynamicpayroad.experiment.DealSource;
import com.cdi.dynamicpayroad.experiment.DealSource.DealRow;
import com.cdi.dynamicpayroad.experiment.EpisodeEngine;
import com.cdi.dynamicpayroad.experiment.ExperimentRunner;
import com.cdi.dynamicpayroad.experiment.ScenarioConfig;
import com.cdi.dynamicpayroad.experiment.bots.CollusionRing.Role;
import com.cdi.dynamicpayroad.redis.RedisTestSupport;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Collusion strategies S1~S4 (ml-design v5 §7.2, card D1) on a real Redis (DB 15), played through
 * the runner's episode loop with n = 8 like the collusion scenario.
 */
class CollusionBotTest extends RedisTestSupport {

    static final BotParams PARAMS = BotParams.read(BotParams.DEFAULT_PATH);
    static final CollusionRing.Params CP = CollusionRing.Params.read(CollusionRing.DEFAULT_PATH);
    static final DealSource DEALS = DealSource.read(DealSource.DEFAULT_PATH);
    static final String REDIS = System.getProperty("payroad.test.redis-url", "redis://localhost:6379/15");
    static final int DEALS_PER_TEST = 150;
    static final double EPS = 1e-6;
    static final Set<Action> BIDS = Set.of(Action.BID_PLACE, Action.BID_UPDATE);

    /** One played deal: its log, the members drawn into it and their roles. */
    record Played(DealRow row, List<ActionLog.Row> rows, List<String> present, Map<String, Role> roles,
                  EpisodeEngine.Result result) {

        boolean together() {
            return present.size() >= 2;
        }

        List<ActionLog.Row> of(String driverId) {
            return rows.stream().filter(a -> a.driverId().equals(driverId)).toList();
        }
    }

    private CollusionRing ring;

    private List<Played> play(CollusionStrategy s, double share, long seed, int deals) {
        List<DriverBot> pool = DriverBot.pool(PARAMS, "C1", seed);
        ring = CollusionRing.form(s, CP, pool, share, seed);
        RiderBot rider = new RiderBot();
        List<DealRow> order = DEALS.shuffled(seed);
        List<Played> out = new ArrayList<>();
        for (int i = 0; i < deals; i++) {
            ActionLog log = new ActionLog("t");
            DealRow row = order.get(i % order.size());
            EpisodeEngine.Result r = ExperimentRunner.episode(market, PARAMS, pool, rider, row, seed, i, CP.nPerDeal(),
                    false, null, log, ring);
            Map<String, Role> roles = new HashMap<>();
            for (String id : ring.present()) roles.put(id, ring.role(id));
            out.add(new Played(row, log.rows(), ring.present(), roles, r));
            ring.endDeal();
        }
        return out;
    }

    /** No bot command breaks R1 or the band: the strategies never ask Lua for something it refuses on price. */
    private static void noPriceRejects(List<Played> played) {
        for (Played p : played) {
            for (ActionLog.Row a : p.rows()) {
                assertThat(a.rejectCode()).as(a.toString()).isNotIn("PRICE_NOT_CONCEDED", "OUT_OF_BAND");
            }
        }
    }

    @Test
    void ringIsTheFirstRoundShareOfThePoolShuffledBySeedPlus777() {
        List<DriverBot> pool = DriverBot.pool(PARAMS, "C1", 3);
        CollusionRing r = CollusionRing.form(CollusionStrategy.S1, CP, pool, 0.3, 3);
        assertThat(r.members()).hasSize(18);
        assertThat(pool.stream().filter(DriverBot::colluder).map(DriverBot::id).toList())
                .containsExactlyElementsOf(r.members());
        assertThat(pool.stream().filter(DriverBot::colluder).map(DriverBot::strategy)).containsOnly("S1");
        assertThat(pool.stream().filter(d -> !d.colluder()).map(DriverBot::strategy))
                .doesNotContain("S1", "S2", "S3", "S4");
        assertThat(CollusionRing.form(CollusionStrategy.S1, CP, DriverBot.pool(PARAMS, "C1", 3), 0.3, 3).members())
                .containsExactlyElementsOf(r.members());
        assertThat(CollusionRing.form(CollusionStrategy.S1, CP, DriverBot.pool(PARAMS, "C1", 3), 0.0, 3).members())
                .isEmpty();
    }

    @Test
    void s1MembersNeverBidBelowTheFloorMultipleNorUnderAFellowMember() {
        List<Played> played = play(CollusionStrategy.S1, 0.5, 1, DEALS_PER_TEST);
        int memberBids = 0, togetherBids = 0;
        for (Played p : played) {
            double minPrice = CP.s1().floorMult() * p.row().basePrice();
            Map<String, Double> live = new HashMap<>();
            for (ActionLog.Row a : p.rows()) {
                if (BIDS.contains(a.action()) && a.accepted() && ring.isMember(a.driverId())) {
                    memberBids++;
                    assertThat(a.price()).as(a.toString()).isGreaterThanOrEqualTo(minPrice - EPS);
                    for (String other : p.present()) {
                        if (other.equals(a.driverId()) || !live.containsKey(other)) continue;
                        togetherBids++;
                        assertThat(a.price()).as("undercut " + other + ": " + a).isGreaterThanOrEqualTo(live.get(other) - EPS);
                    }
                }
                track(live, a);
            }
        }
        assertThat(memberBids).isGreaterThan(50);
        assertThat(togetherBids).isGreaterThan(10);
        noPriceRejects(played);
    }

    @Test
    void s2CoversBidJustAfterTheWinnerAndAreAllWithdrawnBeforeTheDealEnds() {
        List<Played> played = play(CollusionStrategy.S2, 0.5, 1, DEALS_PER_TEST);
        int covers = 0, withdrawn = 0, endedFirst = 0;
        for (Played p : played) {
            if (!p.together()) {
                assertThat(p.roles().values()).containsOnly(Role.BASE);
                continue;
            }
            assertThat(p.roles().values().stream().filter(r -> r == Role.S2_WINNER)).hasSize(1);
            String winner = p.roles().entrySet().stream().filter(e -> e.getValue() == Role.S2_WINNER)
                    .findFirst().orElseThrow().getKey();
            Double winnerFirst = p.of(winner).stream().filter(a -> a.action() == Action.BID_PLACE && a.accepted())
                    .map(ActionLog.Row::tSec).findFirst().orElse(null);
            double firstOffer = p.rows().stream().filter(a -> a.action() == Action.OFFER_POST && a.accepted())
                    .mapToDouble(ActionLog.Row::tSec).findFirst().orElse(Double.POSITIVE_INFINITY);
            double trigger = Math.min(CP.s2().withdrawAtS(), firstOffer);
            for (Map.Entry<String, Role> e : p.roles().entrySet()) {
                if (e.getValue() != Role.S2_COVER) continue;
                List<ActionLog.Row> mine = p.of(e.getKey());
                assertThat(mine).noneMatch(a -> a.action() == Action.ACCEPT_OFFER);
                List<ActionLog.Row> bids = mine.stream().filter(a -> BIDS.contains(a.action()) && a.accepted()).toList();
                if (bids.isEmpty()) continue;
                covers++;
                assertThat(bids).hasSize(1);
                assertThat(winnerFirst).isNotNull();
                assertThat(bids.get(0).tSec() - winnerFirst).isBetween(0.0, CP.s2().coverDelayS() + EPS);
                boolean out = mine.stream().anyMatch(a -> a.action() == Action.WITHDRAW && a.accepted()
                        && a.tSec() >= bids.get(0).tSec());
                if (out) {
                    withdrawn++;
                } else {
                    // Only a deal that closed before the withdrawal moment (150 s or the first offer) may leave a cover up.
                    endedFirst++;
                    assertThat(p.result().durationSec()).as(e.getKey() + " in " + p.row().dealId())
                            .isLessThanOrEqualTo(trigger + EPS);
                }
            }
        }
        System.out.printf("S2 covers=%d withdrawn=%d closed-before-trigger=%d%n", covers, withdrawn, endedFirst);
        assertThat(covers).isGreaterThan(20);
        assertThat(withdrawn).isGreaterThan(covers / 2);
        noPriceRejects(played);
    }

    @Test
    void s3HasExactlyOneCompetingMemberWheneverMembersMeet() {
        List<Played> played = play(CollusionStrategy.S3, 0.5, 1, DEALS_PER_TEST);
        int together = 0, high = 0;
        for (Played p : played) {
            if (!p.together()) {
                assertThat(p.roles().values()).containsOnly(Role.BASE);
                continue;
            }
            together++;
            assertThat(p.roles().values().stream().filter(r -> r == Role.S3_COMPETE)).hasSize(1);
            int competing = 0;
            for (String id : p.present()) {
                List<ActionLog.Row> mine = p.of(id);
                long bids = mine.stream().filter(a -> BIDS.contains(a.action())).count();
                boolean accepted = mine.stream().anyMatch(a -> a.action() == Action.ACCEPT_OFFER);
                switch (p.roles().get(id)) {
                    case S3_ABSTAIN -> assertThat(bids).isZero();
                    case S3_HIGH -> {
                        assertThat(bids).isLessThanOrEqualTo(1);
                        mine.stream().filter(a -> BIDS.contains(a.action())).forEach(a -> assertThat(a.price())
                                .isBetween(1.8 * p.row().basePrice() - EPS, 2.2 * p.row().basePrice() + EPS));
                        high += (int) bids;
                    }
                    default -> {}
                }
                if (p.roles().get(id) != Role.S3_COMPETE) assertThat(accepted).isFalse();
                if (bids > 1 || accepted) competing++;
            }
            assertThat(competing).isLessThanOrEqualTo(1);
        }
        assertThat(together).isGreaterThan(50);
        assertThat(ring.turn()).isEqualTo(together);
        assertThat(high).isGreaterThan(10);
        noPriceRejects(played);
    }

    @Test
    void s4MembersEnterWithinThreeSecondsAtTheLowestHonestBid() {
        List<Played> played = play(CollusionStrategy.S4, 0.5, 1, DEALS_PER_TEST);
        int entries = 0, multi = 0;
        for (Played p : played) {
            Map<String, Double> live = new HashMap<>();
            Map<String, Double> firstAt = new LinkedHashMap<>();
            Double firstHonest = null;
            for (ActionLog.Row a : p.rows()) {
                boolean bid = BIDS.contains(a.action()) && a.accepted();
                if (bid && ring.isMember(a.driverId()) && !firstAt.containsKey(a.driverId())) {
                    Double lowestHonest = live.entrySet().stream().filter(e -> !ring.isMember(e.getKey()))
                            .map(Map.Entry::getValue).min(Double::compare).orElse(null);
                    assertThat(lowestHonest).as("honest bid before " + a).isNotNull();
                    assertThat(a.price()).as(a.toString()).isCloseTo(lowestHonest, org.assertj.core.data.Offset.offset(EPS));
                    assertThat(a.tSec() - firstHonest).isGreaterThanOrEqualTo(CP.s4().waitAfterHonestS()[0] - EPS);
                    firstAt.put(a.driverId(), a.tSec());
                    entries++;
                }
                if (bid && !ring.isMember(a.driverId()) && firstHonest == null) firstHonest = a.tSec();
                track(live, a);
            }
            if (firstAt.size() >= 2) {
                multi++;
                double spread = firstAt.values().stream().mapToDouble(x -> x).max().orElseThrow()
                        - firstAt.values().stream().mapToDouble(x -> x).min().orElseThrow();
                assertThat(spread).isLessThanOrEqualTo(CP.s4().entryWindowS() + EPS);
            }
        }
        assertThat(entries).isGreaterThan(50);
        assertThat(multi).isGreaterThan(10);
        noPriceRejects(played);
    }

    @Test
    void ringShareZeroPlaysExactlyThePlainEpisodes() {
        List<DriverBot> withRing = DriverBot.pool(PARAMS, "C1", 4), plain = DriverBot.pool(PARAMS, "C1", 4);
        CollusionRing empty = CollusionRing.form(CollusionStrategy.S2, CP, withRing, 0.0, 4);
        RiderBot r1 = new RiderBot(), r2 = new RiderBot();
        List<DealRow> order = DEALS.shuffled(4);
        for (int i = 0; i < 40; i++) {
            ActionLog a = new ActionLog("x"), b = new ActionLog("x");
            ExperimentRunner.episode(market, PARAMS, withRing, r1, order.get(i), 4, i, CP.nPerDeal(), false, null, a, empty);
            empty.endDeal();
            ExperimentRunner.episode(market, PARAMS, plain, r2, order.get(i), 4, i, CP.nPerDeal(), false, null, b);
            assertThat(a.rows()).isEqualTo(b.rows());
        }
    }

    /** Ring share 0 with n = 5 gives e2's C1 deals: every column except run_id and scenario. */
    @Test
    void ringShareZeroMatchesE2(@TempDir Path tmp) throws IOException {
        Path c = tmp.resolve("c"), e = tmp.resolve("e");
        ExperimentRunner.run("--scenario", "collusion", "--strategy", "S3", "--ring-shares", "0", "--seed", "1", "--n", "5",
                "--deals-per-run", "30", "--redis-url", REDIS, "--raw-out", c.toString());
        ExperimentRunner.run("--scenario", "e2", "--config", "C1", "--seed", "1", "--deals-per-run", "30",
                "--redis-url", REDIS, "--raw-out", e.toString());
        List<String> cl = Files.readAllLines(c.resolve("deals_out.csv")), el = Files.readAllLines(e.resolve("deals_out.csv"));
        assertThat(cl).hasSize(31).hasSameSizeAs(el);
        for (int i = 1; i < cl.size(); i++) {
            String[] x = cl.get(i).split(",", -1), y = el.get(i).split(",", -1);
            assertThat(x[0]).isEqualTo("S3-r0.0-s1");
            assertThat(x[1]).isEqualTo("collusion");
            assertThat(List.of(x).subList(2, x.length)).isEqualTo(List.of(y).subList(2, y.length));
        }
    }

    @Test
    void scenarioWritesLogsLabelsApartAndTheSameBytesTwice(@TempDir Path tmp) throws IOException {
        Path a = tmp.resolve("a"), b = tmp.resolve("b");
        for (Path out : List.of(a, b)) {
            ExperimentRunner.RunSummary s = ExperimentRunner.run("--scenario", "collusion", "--strategy", "S2",
                    "--ring-shares", "0.3", "--seed", "1", "--deals-per-run", "20", "--redis-url", REDIS,
                    "--raw-out", out.toString());
            assertThat(s.episodes()).isEqualTo(20);
        }
        for (String f : List.of("actions.csv", "deals_out.csv", "labels.csv")) {
            assertThat(Files.readAllBytes(b.resolve(f))).as(f).isEqualTo(Files.readAllBytes(a.resolve(f)));
        }
        List<String> actions = Files.readAllLines(a.resolve("actions.csv"));
        assertThat(actions.get(0)).isEqualTo(String.join(",", CsvExporter.ACTION_COLUMNS)).doesNotContain("colluder", "strategy");
        assertThat(actions).filteredOn(l -> l.contains(",PRESENT,")).hasSize(20 * CP.nPerDeal());
        assertThat(actions.subList(1, actions.size())).allMatch(l -> l.startsWith("S2-r0.3-s1,"));

        List<String> labels = Files.readAllLines(a.resolve("labels.csv"));
        assertThat(labels).hasSize(61);
        assertThat(labels).filteredOn(l -> l.endsWith(",1,S2")).hasSize(18);
        assertThat(Files.readAllLines(a.resolve("deals_out.csv"))).hasSize(21);

        assertThat(ScenarioConfig.parse("--scenario", "collusion", "--strategy", "S1").rawOut())
                .isEqualTo(Path.of("../results/sim/raw/collusion", "S1"));
    }

    /** Live bids by driver from accepted log rows. */
    private static void track(Map<String, Double> live, ActionLog.Row a) {
        if (!a.accepted()) return;
        if (BIDS.contains(a.action())) live.put(a.driverId(), a.price());
        if (a.action() == Action.WITHDRAW) live.remove(a.driverId());
    }
}
