package com.cdi.dynamicpayroad.experiment;

import com.cdi.dynamicpayroad.domain.Deal;
import com.cdi.dynamicpayroad.domain.DealCommand;
import com.cdi.dynamicpayroad.domain.DealEvent;
import com.cdi.dynamicpayroad.domain.DealRules;
import com.cdi.dynamicpayroad.experiment.DealSource.DealRow;
import com.cdi.dynamicpayroad.experiment.bots.BotParams;
import com.cdi.dynamicpayroad.experiment.bots.DriverBot;
import com.cdi.dynamicpayroad.experiment.bots.RiderBot;
import com.cdi.dynamicpayroad.redis.RedisMarket;
import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisURI;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.sync.RedisCommands;

import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.SplittableRandom;

/**
 * Experiment runner entry point (plan v6 §3.3): no Spring, one thread, virtual time, the live
 * service's Lua rules on Redis DB 14. Run with
 * {@code ./gradlew runExperiment --args="--scenario e2"}.
 *
 * <p>{@code smoke} (card C1): one dummy driver bids base_price at t = 5 s and the dummy rider
 * accepts at t = 7 s. {@code e1}~{@code e6} (card C2, ml-design v5 §6.6): the bots of
 * {@code bot-params.json}, every config × seed of the file unless --config / --seed(s) narrow it,
 * all into one deals_out.csv under --raw-out. Their actions.csv keeps only its header: the
 * behaviour log is for the collusion scenarios, and E1~E6 would fill gigabytes with it.
 */
public final class ExperimentRunner {

    static final int SMOKE_DEALS = 10;
    static final String SMOKE_DRIVER_ID = "D-0001";
    static final Set<String> BOT_SCENARIOS = Set.of("e1", "e2", "e3", "e4", "e5", "e6");

    /** What main prints at the end. Wall time goes to stdout only, never into a CSV. */
    public record RunSummary(int episodes, double wallMsPerEpisode) {}

    /** One sweep cell of a scenario: its run_id tag, driver count, rules and fixed τ (null = drawn). */
    record Condition(String tag, int n, DealRules rules, Double tau) {}

    /** How one deal is played; E3 and E6 play every deal twice with the same randomness. */
    record Variant(String mode, String betaMode, boolean fixedPrice, boolean betaOff) {}

    private ExperimentRunner() {}

    public static void main(String[] args) {
        RunSummary s;
        try {
            s = run(args);
        } catch (IllegalArgumentException e) {
            System.err.println("오류: " + e.getMessage());
            System.exit(2);
            return;
        }
        System.out.println(String.format(Locale.ROOT, "EPISODES n=%d wall_ms_per_episode=%.3f",
                s.episodes(), s.wallMsPerEpisode()));
    }

    public static RunSummary run(String... args) {
        ScenarioConfig cfg = ScenarioConfig.parse(args);
        boolean smoke = cfg.scenario().equals("smoke");
        if (!smoke && !BOT_SCENARIOS.contains(cfg.scenario())) {
            throw new IllegalArgumentException("not implemented (C3~C5, D1): " + cfg.scenario());
        }
        DealSource source = DealSource.read(cfg.deals());
        BotParams params = smoke ? null : BotParams.read(BotParams.DEFAULT_PATH);

        RedisURI uri = RedisURI.create(cfg.redisUrl());
        RedisClient client = RedisClient.create(uri);
        try (StatefulRedisConnection<String, String> conn = client.connect();
             CsvExporter csv = new CsvExporter(cfg.rawOut())) {
            if (smoke) return smoke(cfg, source, new RedisMarket(conn.sync(), uri.getDatabase(), cfg.rules()), csv);
            return bots(cfg, params, source, conn.sync(), uri.getDatabase(), csv);
        } finally {
            client.shutdown();
        }
    }

    private static RunSummary smoke(ScenarioConfig cfg, DealSource source, RedisMarket market, CsvExporter csv) {
        int perRun = cfg.dealsPerRun() == null ? SMOKE_DEALS : cfg.dealsPerRun();
        int episodes = 0;
        long nanos = 0;
        for (long seed : cfg.seedsOr(List.of(ScenarioConfig.DEFAULT_SEED))) {
            String runId = "smoke-s" + seed;
            CsvExporter.RunMeta meta = new CsvExporter.RunMeta(runId, cfg.scenario(), cfg.config(), seed,
                    market.rules(), cfg.tau());
            ActionLog log = new ActionLog(runId);
            List<DealRow> order = source.shuffled(seed);
            SmokeDriver driver = new SmokeDriver(SMOKE_DRIVER_ID);
            csv.writeLabels(runId, List.of(driver));
            for (int i = 0; i < perRun; i++) {
                DealRow row = order.get(i % order.size());
                List<Agent> agents = List.of(new SmokeRider(), driver);
                long t0 = System.nanoTime();
                EpisodeEngine.Result r = new EpisodeEngine(market, row, agents, seed, i, log).run();
                nanos += System.nanoTime() - t0;
                episodes++;
                csv.writeDeal(meta, r);
                csv.writeActions(log);
            }
        }
        return new RunSummary(episodes, episodes == 0 ? 0 : nanos / 1e6 / episodes);
    }

    /** e1~e6: config → seed → sweep cell → deal → variant, in that fixed order. */
    private static RunSummary bots(ScenarioConfig cfg, BotParams params, DealSource source,
                                   RedisCommands<String, String> cmd, int db, CsvExporter csv) {
        String scenario = cfg.scenario();
        List<String> configs = cfg.config() != null ? List.of(cfg.config())
                : scenario.equals("e4") ? params.sweeps().e4Configs() : List.copyOf(params.configs().keySet());
        List<Long> seeds = cfg.seedsOr(params.seedList());
        int perRun = cfg.dealsPerRun() != null ? cfg.dealsPerRun() : params.dealsPerRun();
        List<Condition> conditions = conditions(cfg, params);
        List<Variant> variants = variants(cfg);
        for (Condition c : conditions) {
            if (c.n() > params.poolSize()) throw new IllegalArgumentException("--n is larger than the pool: " + c.n());
        }

        Map<DealRules, RedisMarket> markets = new HashMap<>();
        RiderBot rider = new RiderBot();
        int episodes = 0;
        long nanos = 0;
        for (String config : configs) {
            for (long seed : seeds) {
                List<DriverBot> pool = DriverBot.pool(params, config, seed);
                List<DealRow> order = order(source, seed, scenario.equals("e6"));
                for (Condition c : conditions) {
                    String runId = scenario + "-" + config + (c.tag().isEmpty() ? "" : "-" + c.tag()) + "-s" + seed;
                    RedisMarket market = markets.computeIfAbsent(c.rules(), r -> new RedisMarket(cmd, db, r));
                    CsvExporter.RunMeta meta = new CsvExporter.RunMeta(runId, scenario, config, seed, c.rules(), c.tau());
                    ActionLog log = new ActionLog(runId);
                    csv.writeLabels(runId, pool);
                    for (int i = 0; i < perRun; i++) {
                        DealRow row = order.get(i % order.size());
                        for (Variant v : variants) {
                            long t0 = System.nanoTime();
                            EpisodeEngine.Result r = episode(market, params, pool, rider, v.betaOff() ? dry(row) : row,
                                    seed, i, c.n(), v.fixedPrice(), c.tau(), log);
                            nanos += System.nanoTime() - t0;
                            episodes++;
                            csv.writeDeal(meta, r, v.mode(), v.betaMode());
                            log.clear();
                        }
                    }
                }
            }
        }
        return new RunSummary(episodes, episodes == 0 ? 0 : nanos / 1e6 / episodes);
    }

    /**
     * One bot episode. Every draw comes from {@link EpisodeEngine#episodeRng} in this order: a full
     * shuffle of the pool (the first n drivers take part), the rider's values, then each chosen
     * driver's values. The counts never depend on the variant, so the same (seed, dealIndex) gets
     * the same randomness in every condition, and the first k drivers are the same for every n ≥ k.
     */
    public static EpisodeEngine.Result episode(RedisMarket market, BotParams params, List<DriverBot> pool,
                                               RiderBot rider, DealRow row, long seed, int dealIndex, int n,
                                               boolean fixedPrice, Double tau, ActionLog log) {
        SplittableRandom rng = EpisodeEngine.episodeRng(seed, dealIndex);
        int[] idx = new int[pool.size()];
        for (int i = 0; i < idx.length; i++) idx[i] = i;
        for (int i = idx.length - 1; i > 0; i--) {
            int j = rng.nextInt(i + 1);
            int t = idx[i];
            idx[i] = idx[j];
            idx[j] = t;
        }
        rider.prepare(params, row, fixedPrice, tau, rng);
        DealRules rules = market.rules();
        List<Agent> agents = new ArrayList<>(n + 1);
        agents.add(rider);
        for (int k = 0; k < n; k++) {
            DriverBot d = pool.get(idx[k]);
            d.prepare(params, row, rules.bandMinRatio(), rules.bandMaxRatio(), fixedPrice, rng);
            agents.add(d);
        }
        return new EpisodeEngine(market, row, agents, rng, dealIndex, log).run();
    }

    static List<Condition> conditions(ScenarioConfig cfg, BotParams params) {
        BotParams.Sweeps sw = params.sweeps();
        int n = cfg.n() != null ? cfg.n() : params.defaultN();
        List<Condition> out = new ArrayList<>();
        switch (cfg.scenario()) {
            case "e1" -> {
                for (int k : cfg.n() != null ? List.of(cfg.n()) : sw.e1N()) {
                    out.add(new Condition("n" + k, k, cfg.rules(), cfg.tau()));
                }
            }
            case "e4" -> {
                DealRules d = DealRules.defaults();
                for (int ttl : cfg.offerTtlSec() != null ? List.of(cfg.offerTtlSec()) : sw.e4OfferTtl()) {
                    for (int limit : cfg.roundLimit() != null ? List.of(cfg.roundLimit()) : sw.e4RoundLimit()) {
                        DealRules rules = new DealRules(d.bandMinRatio(), d.bandMaxRatio(), d.dealTtl(),
                                Duration.ofSeconds(ttl), limit, d.avgSpeedKmh(), d.detourFactor(), d.maxActiveBids(),
                                d.presenceTtl());
                        out.add(new Condition("ttl" + ttl + "-rl" + limit, n, rules, cfg.tau()));
                    }
                }
            }
            case "e5" -> {
                for (double tau : cfg.tau() != null ? List.of(cfg.tau()) : sw.e5Tau()) {
                    out.add(new Condition(String.format(Locale.ROOT, "tau%.2f", tau), n, cfg.rules(), tau));
                }
            }
            default -> out.add(new Condition("", n, cfg.rules(), cfg.tau()));
        }
        return out;
    }

    static List<Variant> variants(ScenarioConfig cfg) {
        return switch (cfg.scenario()) {
            case "e3" -> List.of(new Variant("bargain", null, false, false), new Variant("fixed", null, true, false));
            case "e6" -> cfg.betaOff() ? List.of(new Variant(null, "off", false, true))
                    : List.of(new Variant(null, "on", false, false), new Variant(null, "off", false, true));
            default -> List.of(cfg.betaOff() ? new Variant(null, "off", false, true) : new Variant(null, null, false, false));
        };
    }

    /** The run's deal order: {@link DealSource#shuffled}, keeping only wet deals for E6. */
    private static List<DealRow> order(DealSource source, long seed, boolean wetOnly) {
        List<DealRow> order = source.shuffled(seed);
        if (!wetOnly) return order;
        List<DealRow> wet = order.stream().filter(DealRow::wet).toList();
        if (wet.isEmpty()) throw new IllegalArgumentException("e6 needs wet = 1 deals; the deals CSV has none");
        return wet;
    }

    /** β off (E6): base_price = base_dry, and the beta column says 1. */
    private static DealRow dry(DealRow r) {
        return new DealRow(r.dealId(), r.distanceKm(), r.originLat(), r.originLng(), r.baseDry(), 1.0, r.baseDry(),
                r.wet());
    }


    /** Bids base_price at t = 5 s. */
    static final class SmokeDriver implements Agent {
        private final String id;

        SmokeDriver(String id) {
            this.id = id;
        }

        @Override public String id() { return id; }
        @Override public ActorType actorType() { return ActorType.DRIVER; }
        @Override public String strategy() { return "DUMMY"; }

        @Override
        public void onStart(EpisodeContext ctx) {
            DealRow row = ctx.row();
            ctx.schedule(5.0, () -> ctx.submit(
                    new DealCommand.PlaceBid(id, row.basePrice(), row.originLat(), row.originLng(), null)));
        }

        @Override
        public void onEvent(EpisodeContext ctx, DealEvent e) {}
    }

    /** Accepts the cheapest live bid at t = 7 s. */
    static final class SmokeRider implements Agent {
        @Override public String id() { return EpisodeEngine.RIDER_ID; }
        @Override public ActorType actorType() { return ActorType.RIDER; }

        @Override
        public void onStart(EpisodeContext ctx) {
            ctx.schedule(7.0, () -> {
                List<Deal.Bid> bids = ctx.deal().bidsAscending();
                if (!bids.isEmpty()) ctx.submit(new DealCommand.AcceptBid(id(), bids.get(0).bidId(), null));
            });
        }

        @Override
        public void onEvent(EpisodeContext ctx, DealEvent e) {}
    }
}
