package com.cdi.dynamicpayroad.experiment;

import com.cdi.dynamicpayroad.domain.DealCommand;
import com.cdi.dynamicpayroad.domain.DealEvent;
import com.cdi.dynamicpayroad.domain.DealStatus;
import com.cdi.dynamicpayroad.domain.Enums.EndReason;
import com.cdi.dynamicpayroad.domain.Enums.MatchPath;
import com.cdi.dynamicpayroad.experiment.ActionLog.Action;
import com.cdi.dynamicpayroad.experiment.DealSource.DealRow;
import com.cdi.dynamicpayroad.redis.RedisTestSupport;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/** The episode engine on a real Redis (DB 15), with the smoke scenario and small scripted bots. */
class EpisodeEngineTest extends RedisTestSupport {

    static final String REDIS = System.getProperty("payroad.test.redis-url", "redis://localhost:6379/15");
    static final String DEALS = "src/test/resources/experiment/deals_small.csv";
    static final DealRow ROW = new DealRow("S-T", 10.0, 12.97, 77.59, 180.0, 1.1, 198.0, true);

    @Test
    void smokeMatchesEveryDealAtBasePriceAfterSevenSeconds(@TempDir Path tmp) throws IOException {
        ExperimentRunner.RunSummary s = ExperimentRunner.run("--scenario", "smoke", "--seed", "1", "--deals", DEALS,
                "--redis-url", REDIS, "--raw-out", tmp.toString());

        assertThat(s.episodes()).isEqualTo(10);
        List<Map<String, String>> deals = read(tmp.resolve("deals_out.csv"));
        assertThat(Files.readAllLines(tmp.resolve("deals_out.csv")).get(0))
                .isEqualTo(String.join(",", CsvExporter.DEAL_COLUMNS));
        assertThat(deals).hasSize(10);
        for (Map<String, String> d : deals) {
            assertThat(d.get("status")).isEqualTo("MATCHED");
            assertThat(Double.parseDouble(d.get("markup"))).isEqualTo(1.0);
            assertThat(Double.parseDouble(d.get("duration_sec"))).isEqualTo(7.0);
            assertThat(d.get("match_path")).isEqualTo("RIDER_PICKED_BID");
            assertThat(d.get("chosen_rank")).isEqualTo("1");
            assertThat(d.get("winner_id")).isEqualTo(ExperimentRunner.SMOKE_DRIVER_ID);
            assertThat(d.get("winner_strategy")).isEqualTo("DUMMY");
            assertThat(d.get("winner_is_colluder")).isEqualTo("0");
            assertThat(d.get("round_count")).isEqualTo("1");
            assertThat(d.get("bidder_count")).isEqualTo("1");
            assertThat(d.get("n_drivers")).isEqualTo("1");
            assertThat(d.get("param_offer_ttl")).isEqualTo("30");
            assertThat(d.get("param_round_limit")).isEqualTo("20");
            assertThat(d.get("end_reason")).isEmpty();
        }
        assertThat(deals.stream().map(d -> d.get("deal_index")).toList())
                .containsExactly("0", "1", "2", "3", "4", "5", "6", "7", "8", "9");

        // Per deal: PRESENT at 0, BID_PLACE at 5, ACCEPT_BID at 7.
        List<Map<String, String>> actions = read(tmp.resolve("actions.csv"));
        assertThat(actions).hasSize(30);
        assertThat(actions.subList(0, 3).stream().map(a -> a.get("t_sec") + " " + a.get("actor_type") + " "
                + a.get("action") + " " + a.get("accepted")).toList())
                .containsExactly("0.000 DRIVER PRESENT 1", "5.000 DRIVER BID_PLACE 1", "7.000 RIDER ACCEPT_BID 1");
        assertThat(actions.get(2).get("driver_id")).isEqualTo(EpisodeEngine.RIDER_ID);
        assertThat(actions.get(1).get("price")).isEqualTo(actions.get(2).get("price"));

        assertThat(read(tmp.resolve("labels.csv"))).singleElement()
                .satisfies(l -> assertThat(l).containsEntry("run_id", "smoke-s1").containsEntry("driver_id", "D-0001")
                        .containsEntry("is_colluder", "0").containsEntry("strategy", "DUMMY"));
    }

    @Test
    void dealWithoutBidsExpiresByTheScheduledSweepAtTtl() {
        ActionLog log = new ActionLog("t");
        Scripted rider = Scripted.rider(Map.of());
        Scripted driver = Scripted.driver("D-1", Map.of());

        EpisodeEngine.Result r = new EpisodeEngine(market, ROW, List.of(rider, driver), 1, 0, log).run();

        assertThat(r.deal().status()).isEqualTo(DealStatus.EXPIRED);
        assertThat(r.deal().endReason()).isEqualTo(EndReason.TTL);
        assertThat(r.durationSec()).isEqualTo(180.0);
        assertThat(driver.seen).containsExactly("180.000 deal.expired");
    }

    @Test
    void offerIsSeenByDriversAndExpiresByTheSweepAtItsOwnExpiry() {
        ActionLog log = new ActionLog("t");
        Scripted rider = Scripted.rider(Map.of(10.0, c -> new DealCommand.PostOffer(EpisodeEngine.RIDER_ID, 150.0, null)));
        Scripted d1 = Scripted.driver("D-1", Map.of());
        Scripted d2 = Scripted.driver("D-2", Map.of());

        new EpisodeEngine(market, ROW, List.of(rider, d1, d2), 1, 0, log).run();

        assertThat(d1.seen).containsExactly("10.000 offer.posted", "40.000 offer.expired", "180.000 deal.expired");
        assertThat(log.rows().stream().filter(a -> a.action() == Action.OFFER_SEEN).map(ActionLog.Row::driverId))
                .containsExactly("D-1", "D-2");
        assertThat(log.rows().stream().filter(a -> a.action() == Action.OFFER_POST)).singleElement()
                .satisfies(a -> assertThat(a.price()).isEqualTo(150.0));
    }

    @Test
    void driverTakesOfferAndLaterActionsAreDropped() {
        ActionLog log = new ActionLog("t");
        Scripted rider = Scripted.rider(Map.of(
                3.0, c -> new DealCommand.PostOffer(EpisodeEngine.RIDER_ID, 170.0, null),
                9.0, c -> new DealCommand.PostOffer(EpisodeEngine.RIDER_ID, 180.0, null)));
        Scripted driver = Scripted.driver("D-1", Map.of(
                2.0, c -> new DealCommand.PlaceBid("D-1", 250.0, ROW.originLat(), ROW.originLng(), null),
                4.0, c -> new DealCommand.PlaceBid("D-1", 240.0, ROW.originLat(), ROW.originLng(), null),
                5.0, c -> new DealCommand.AcceptOffer("D-1", null)));

        EpisodeEngine.Result r = new EpisodeEngine(market, ROW, List.of(rider, driver), 1, 0, log).run();

        assertThat(r.deal().status()).isEqualTo(DealStatus.MATCHED);
        assertThat(r.deal().match().matchPath()).isEqualTo(MatchPath.DRIVER_TOOK_OFFER);
        assertThat(r.deal().match().finalPrice()).isEqualTo(170.0);
        assertThat(r.durationSec()).isEqualTo(5.0);
        assertThat(log.rows().stream().map(a -> a.action() + "@" + a.tSec()).toList()).containsExactly(
                "PRESENT@0.0", "BID_PLACE@2.0", "OFFER_POST@3.0", "OFFER_SEEN@3.0", "BID_UPDATE@4.0",
                "ACCEPT_OFFER@5.0");
        assertThat(log.rows().get(5).price()).isEqualTo(170.0);
    }

    @Test
    void rejectedCommandsAreLoggedWithTheirCode() {
        ActionLog log = new ActionLog("t");
        Scripted rider = Scripted.rider(Map.of());
        Scripted driver = Scripted.driver("D-1", Map.of(
                1.0, c -> new DealCommand.PlaceBid("D-1", 1000.0, ROW.originLat(), ROW.originLng(), null),
                2.0, c -> new DealCommand.WithdrawBid("D-1", null)));

        new EpisodeEngine(market, ROW, List.of(rider, driver), 1, 0, log).run();

        assertThat(log.rows().subList(1, 3).stream().map(a -> a.action() + " " + a.accepted() + " " + a.rejectCode()))
                .containsExactly("BID_PLACE false OUT_OF_BAND", "WITHDRAW false BID_NOT_FOUND");
    }

    @Test
    void rngIsFixedBySeedAndDealIndex() {
        long a = new EpisodeEngine(market, ROW, List.of(), 7, 3, new ActionLog("t")).rng().nextLong();
        long b = new EpisodeEngine(market, ROW, List.of(), 7, 3, new ActionLog("t")).rng().nextLong();
        long c = new EpisodeEngine(market, ROW, List.of(), 7, 4, new ActionLog("t")).rng().nextLong();
        assertThat(a).isEqualTo(b).isNotEqualTo(c);
    }

    @Test
    void argumentsAreCheckedBeforeRedisIsTouched() {
        assertThatThrownBy(() -> ExperimentRunner.run("--scenario", "e8"))
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("not implemented (C3~C5, D1)");
        assertThatThrownBy(() -> ExperimentRunner.run("--scenario", "smoke", "--bogus", "1"))
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("unknown argument");
        assertThatThrownBy(() -> ExperimentRunner.run("--scenario", "smoke", "--redis-url", "redis://localhost:6379/0"))
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("DB 0(실서비스)에서는 실행하지 않습니다");
        assertThatThrownBy(() -> ExperimentRunner.run("--seed", "1"))
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("--scenario");
        assertThat(ScenarioConfig.parse("--scenario", "x", "--seeds", "1-3").seeds()).containsExactly(1L, 2L, 3L);
        assertThat(ScenarioConfig.parse("--scenario", "x", "--offer-ttl", "10", "--round-limit", "5").rules())
                .satisfies(rl -> {
                    assertThat(rl.offerTtl().toSeconds()).isEqualTo(10);
                    assertThat(rl.roundLimit()).isEqualTo(5);
                });
    }

    @Test
    void dealSourceFindsColumnsByHeaderName(@TempDir Path tmp) throws IOException {
        Path f = tmp.resolve("d.csv");
        Files.writeString(f, "wet,base_price,extra,beta,base_dry,origin_lng,origin_lat,distance_km,deal_id\n"
                + "0,120.5,x,1.0,120.5,77.6,12.9,6.0,S9\n");
        assertThat(DealSource.read(f).rows())
                .containsExactly(new DealRow("S9", 6.0, 12.9, 77.6, 120.5, 1.0, 120.5, false));
        assertThat(DealSource.read(Path.of(DEALS)).shuffled(3)).isEqualTo(DealSource.read(Path.of(DEALS)).shuffled(3));
    }

    /** A bot that sends fixed commands at fixed times and records the events it sees. */
    static final class Scripted implements Agent {
        final String id;
        final ActorType type;
        final Map<Double, Function<EpisodeContext, DealCommand>> plan;
        final List<String> seen = new ArrayList<>();

        private Scripted(String id, ActorType type, Map<Double, Function<EpisodeContext, DealCommand>> plan) {
            this.id = id;
            this.type = type;
            this.plan = plan;
        }

        static Scripted rider(Map<Double, Function<EpisodeContext, DealCommand>> plan) {
            return new Scripted(EpisodeEngine.RIDER_ID, ActorType.RIDER, plan);
        }

        static Scripted driver(String id, Map<Double, Function<EpisodeContext, DealCommand>> plan) {
            return new Scripted(id, ActorType.DRIVER, plan);
        }

        @Override public String id() { return id; }
        @Override public ActorType actorType() { return type; }

        @Override
        public void onStart(EpisodeContext ctx) {
            plan.keySet().stream().sorted().forEach(t -> ctx.schedule(t, () -> ctx.submit(plan.get(t).apply(ctx))));
        }

        @Override
        public void onEvent(EpisodeContext ctx, DealEvent e) {
            seen.add(String.format(java.util.Locale.ROOT, "%.3f %s", ctx.elapsedSec(), e.name()));
        }
    }

    private static List<Map<String, String>> read(Path file) throws IOException {
        List<String> lines = Files.readAllLines(file);
        String[] header = lines.get(0).split(",", -1);
        List<Map<String, String>> out = new ArrayList<>();
        for (String line : lines.subList(1, lines.size())) {
            String[] f = line.split(",", -1);
            Map<String, String> m = new LinkedHashMap<>();
            for (int i = 0; i < header.length; i++) m.put(header[i], f[i]);
            out.add(m);
        }
        return out;
    }
}
