package com.cdi.dynamicpayroad.experiment;

import com.cdi.dynamicpayroad.domain.Deal;
import com.cdi.dynamicpayroad.domain.DealCommand;
import com.cdi.dynamicpayroad.domain.DealEvent;
import com.cdi.dynamicpayroad.domain.DealRules;
import com.cdi.dynamicpayroad.experiment.DealSource.DealRow;
import com.cdi.dynamicpayroad.experiment.bots.BotParams;
import com.cdi.dynamicpayroad.experiment.bots.CollusionRing;
import com.cdi.dynamicpayroad.experiment.bots.CollusionStrategy;
import com.cdi.dynamicpayroad.experiment.bots.DriverBot;
import com.cdi.dynamicpayroad.experiment.bots.RiderBot;
import com.cdi.dynamicpayroad.redis.RedisMarket;
import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisURI;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.sync.RedisCommands;

import java.time.Duration;
import java.util.ArrayList;
import java.util.Comparator;
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
 *
 * <p>{@code diag-var} (card C3, ml-design v5 §6.5 variance test): the deal with the median
 * base_price, n = 5, C1, played once per seed 1~100.
 *
 * <p>{@code e7} (card C5, ml-design v5 §6.6 E7): n = 5, configs C1~C4, seeds of bot-params.json,
 * ring shares {0, 0.1, 0.3, 0.5} (or --ring-shares) × strategies S1~S4 (or --strategy). With no ring
 * member the strategy changes nothing, so share 0 is played once per config × seed as the shared
 * baseline: run_id {@code e7-<config>-r0.0-s<seed>}, the others {@code e7-<config>-<strategy>-r<share>-s<seed>}.
 * Same randomness for the same (seed, deal index) in every cell; deals_out.csv only.
 *
 * <p>{@code collusion} (card D1, ml-design v5 §7.1): honest drivers in C1 shares, a ring of
 * round(share × 60) drivers playing --strategy, n = 8 and 1,000 deals per run from
 * {@code collusion-params.json}. Writes the full behaviour log: actions.csv, deals_out.csv and
 * labels.csv under --raw-out (default ../results/sim/raw/collusion/&lt;strategy&gt;/), run_id
 * {@code <strategy>-r<share>-s<seed>}.
 */
public final class ExperimentRunner {

    static final int SMOKE_DEALS = 10;
    static final String SMOKE_DRIVER_ID = "D-0001";
    static final Set<String> BOT_SCENARIOS = Set.of("e1", "e2", "e3", "e4", "e5", "e6");
    static final String DIAG_VAR = "diag-var";
    static final int DIAG_N = 5;
    static final String DIAG_CONFIG = "C1";
    static final long DIAG_SEEDS = 100;
    static final String COLLUSION = "collusion";
    static final String COLLUSION_CONFIG = "C1";
    static final String E7 = "e7";
    static final List<Double> E7_SHARES = List.of(0.0, 0.1, 0.3, 0.5);
    static final List<CollusionStrategy> E7_STRATEGIES =
            List.of(CollusionStrategy.S1, CollusionStrategy.S2, CollusionStrategy.S3, CollusionStrategy.S4);

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
        boolean diag = cfg.scenario().equals(DIAG_VAR);
        boolean collusion = cfg.scenario().equals(COLLUSION);
        boolean e7 = cfg.scenario().equals(E7);
        if (!smoke && !diag && !collusion && !e7 && !BOT_SCENARIOS.contains(cfg.scenario())) {
            throw new IllegalArgumentException("not implemented (C3~C5, D1): " + cfg.scenario());
        }
        CollusionRing.Params collusionParams = null;
        CollusionStrategy strategy = null;
        if (collusion) {
            if (cfg.strategy() == null) throw new IllegalArgumentException("collusion needs --strategy S1|S2|S3|S4");
            strategy = CollusionStrategy.valueOf(cfg.strategy());
            collusionParams = CollusionRing.Params.read(CollusionRing.DEFAULT_PATH);
        }
        if (e7) {
            if (cfg.strategy() != null && E7_STRATEGIES.stream().noneMatch(x -> x.name().equals(cfg.strategy()))) {
                throw new IllegalArgumentException("e7 takes --strategy S1|S2|S3|S4: " + cfg.strategy());
            }
            collusionParams = CollusionRing.Params.read(CollusionRing.DEFAULT_PATH);
        }
        DealSource source = DealSource.read(cfg.deals());
        BotParams params = smoke ? null : BotParams.read(BotParams.DEFAULT_PATH);

        RedisURI uri = RedisURI.create(cfg.redisUrl());
        RedisClient client = RedisClient.create(uri);
        try (StatefulRedisConnection<String, String> conn = client.connect();
             CsvExporter csv = new CsvExporter(cfg.rawOut())) {
            if (smoke) return smoke(cfg, source, new RedisMarket(conn.sync(), uri.getDatabase(), cfg.rules()), csv);
            if (diag) return diagVar(cfg, params, source, new RedisMarket(conn.sync(), uri.getDatabase(), cfg.rules()), csv);
            if (collusion) return collusion(cfg, params, collusionParams, strategy, source,
                    new RedisMarket(conn.sync(), uri.getDatabase(), cfg.rules()), csv);
            if (e7) return e7(cfg, params, collusionParams, source,
                    new RedisMarket(conn.sync(), uri.getDatabase(), cfg.rules()), csv);
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

    /** diag-var: one deal (the median base_price), n = 5, C1, deal index 0 under every seed. */
    private static RunSummary diagVar(ScenarioConfig cfg, BotParams params, DealSource source, RedisMarket market,
                                      CsvExporter csv) {
        String config = cfg.config() != null ? cfg.config() : DIAG_CONFIG;
        int n = cfg.n() != null ? cfg.n() : DIAG_N;
        if (n > params.poolSize()) throw new IllegalArgumentException("--n is larger than the pool: " + n);
        List<Long> seeds = new ArrayList<>();
        for (long s = 1; s <= DIAG_SEEDS; s++) seeds.add(s);
        DealRow row = medianRow(source);
        RiderBot rider = new RiderBot();
        int episodes = 0;
        long nanos = 0;
        for (long seed : cfg.seedsOr(seeds)) {
            String runId = DIAG_VAR + "-" + config + "-s" + seed;
            CsvExporter.RunMeta meta = new CsvExporter.RunMeta(runId, DIAG_VAR, config, seed, market.rules(), cfg.tau());
            ActionLog log = new ActionLog(runId);
            List<DriverBot> pool = DriverBot.pool(params, config, seed);
            csv.writeLabels(runId, pool);
            long t0 = System.nanoTime();
            EpisodeEngine.Result r = episode(market, params, pool, rider, row, seed, 0, n, false, cfg.tau(), log);
            nanos += System.nanoTime() - t0;
            episodes++;
            csv.writeDeal(meta, r);
        }
        return new RunSummary(episodes, episodes == 0 ? 0 : nanos / 1e6 / episodes);
    }

    /** The row whose base_price is the median; with an even count the lower one. Ties keep file order. */
    static DealRow medianRow(DealSource source) {
        List<DealRow> sorted = new ArrayList<>(source.rows());
        sorted.sort(Comparator.comparingDouble(DealRow::basePrice));
        return sorted.get((sorted.size() - 1) / 2);
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

    /** collusion: share → seed → deal; every episode's behaviour log goes to actions.csv. */
    private static RunSummary collusion(ScenarioConfig cfg, BotParams params, CollusionRing.Params cp,
                                        CollusionStrategy strategy, DealSource source, RedisMarket market,
                                        CsvExporter csv) {
        if (cp.poolSize() != params.poolSize()) {
            throw new IllegalArgumentException("collusion-params pool_size " + cp.poolSize()
                    + " differs from bot-params pool_size " + params.poolSize());
        }
        CollusionRing.Params.Grid grid = cp.grid(strategy);
        List<Double> shares = cfg.ringShares() != null ? cfg.ringShares() : grid.ringShares();
        for (double share : shares) {
            if (!(share >= 0 && share <= 1)) throw new IllegalArgumentException("--ring-shares must be in [0, 1]: " + share);
        }
        List<Long> defaultSeeds = new ArrayList<>();
        for (long s = grid.seeds().get(0); s <= grid.seeds().get(1); s++) defaultSeeds.add(s);
        int n = cfg.n() != null ? cfg.n() : cp.nPerDeal();
        if (n > params.poolSize()) throw new IllegalArgumentException("--n is larger than the pool: " + n);
        int perRun = cfg.dealsPerRun() != null ? cfg.dealsPerRun() : cp.dealsPerRun();

        RiderBot rider = new RiderBot();
        int episodes = 0;
        long nanos = 0;
        for (double share : shares) {
            for (long seed : cfg.seedsOr(defaultSeeds)) {
                String runId = strategy + "-r" + share + "-s" + seed;
                List<DriverBot> pool = DriverBot.pool(params, COLLUSION_CONFIG, seed);
                CollusionRing ring = CollusionRing.form(strategy, cp, pool, share, seed);
                CsvExporter.RunMeta meta = new CsvExporter.RunMeta(runId, COLLUSION, COLLUSION_CONFIG, seed,
                        market.rules(), cfg.tau());
                ActionLog log = new ActionLog(runId);
                csv.writeLabels(runId, pool);
                List<DealRow> order = source.shuffled(seed);
                for (int i = 0; i < perRun; i++) {
                    long t0 = System.nanoTime();
                    EpisodeEngine.Result r = episode(market, params, pool, rider, order.get(i % order.size()), seed, i,
                            n, false, cfg.tau(), log, ring);
                    ring.endDeal();
                    nanos += System.nanoTime() - t0;
                    episodes++;
                    csv.writeDeal(meta, r);
                    csv.writeActions(log);
                }
            }
        }
        return new RunSummary(episodes, episodes == 0 ? 0 : nanos / 1e6 / episodes);
    }

    /** e7: config → seed → (share 0 once, then strategy × share) → deal. Behaviour log is not kept. */
    private static RunSummary e7(ScenarioConfig cfg, BotParams params, CollusionRing.Params cp, DealSource source,
                                 RedisMarket market, CsvExporter csv) {
        List<String> configs = cfg.config() != null ? List.of(cfg.config()) : List.copyOf(params.configs().keySet());
        List<Double> shares = cfg.ringShares() != null ? cfg.ringShares() : E7_SHARES;
        for (double share : shares) {
            if (!(share >= 0 && share <= 1)) throw new IllegalArgumentException("--ring-shares must be in [0, 1]: " + share);
        }
        List<CollusionStrategy> strategies = cfg.strategy() != null
                ? List.of(CollusionStrategy.valueOf(cfg.strategy())) : E7_STRATEGIES;
        int n = cfg.n() != null ? cfg.n() : params.defaultN();
        if (n > params.poolSize()) throw new IllegalArgumentException("--n is larger than the pool: " + n);
        int perRun = cfg.dealsPerRun() != null ? cfg.dealsPerRun() : params.dealsPerRun();

        RiderBot rider = new RiderBot();
        int episodes = 0;
        long nanos = 0;
        for (String config : configs) {
            for (long seed : cfg.seedsOr(params.seedList())) {
                List<DealRow> order = source.shuffled(seed);
                // (strategy or null for the shared baseline, share) cells of this config × seed
                List<Map.Entry<CollusionStrategy, Double>> cells = new ArrayList<>();
                if (shares.contains(0.0)) cells.add(new java.util.AbstractMap.SimpleEntry<>(null, 0.0));
                for (CollusionStrategy s : strategies) {
                    for (double share : shares) if (share != 0.0) cells.add(new java.util.AbstractMap.SimpleEntry<>(s, share));
                }
                for (Map.Entry<CollusionStrategy, Double> c : cells) {
                    CollusionStrategy s = c.getKey();
                    double share = c.getValue();
                    String runId = E7 + "-" + config + (s == null ? "" : "-" + s) + "-r" + share + "-s" + seed;
                    List<DriverBot> pool = DriverBot.pool(params, config, seed);
                    CollusionRing ring = CollusionRing.form(s == null ? CollusionStrategy.S1 : s, cp, pool, share, seed);
                    CsvExporter.RunMeta meta = new CsvExporter.RunMeta(runId, E7, config, seed, market.rules(), cfg.tau());
                    ActionLog log = new ActionLog(runId);
                    csv.writeLabels(runId, pool);
                    for (int i = 0; i < perRun; i++) {
                        long t0 = System.nanoTime();
                        EpisodeEngine.Result r = episode(market, params, pool, rider, order.get(i % order.size()), seed,
                                i, n, false, cfg.tau(), log, ring);
                        ring.endDeal();
                        nanos += System.nanoTime() - t0;
                        episodes++;
                        csv.writeDeal(meta, r);
                        log.clear();
                    }
                }
            }
        }
        return new RunSummary(episodes, episodes == 0 ? 0 : nanos / 1e6 / episodes);
    }

    public static EpisodeEngine.Result episode(RedisMarket market, BotParams params, List<DriverBot> pool,
                                               RiderBot rider, DealRow row, long seed, int dealIndex, int n,
                                               boolean fixedPrice, Double tau, ActionLog log) {
        return episode(market, params, pool, rider, row, seed, dealIndex, n, fixedPrice, tau, log, null);
    }

    /**
     * One bot episode. Every draw comes from {@link EpisodeEngine#episodeRng} in this order: a full
     * shuffle of the pool (the first n drivers take part), the rider's values, then each chosen
     * driver's values. The counts never depend on the variant, so the same (seed, dealIndex) gets
     * the same randomness in every condition, and the first k drivers are the same for every n ≥ k.
     * A {@code ring} (null = none) is told the chosen drivers last; it draws from its own stream.
     */
    public static EpisodeEngine.Result episode(RedisMarket market, BotParams params, List<DriverBot> pool,
                                               RiderBot rider, DealRow row, long seed, int dealIndex, int n,
                                               boolean fixedPrice, Double tau, ActionLog log, CollusionRing ring) {
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
        if (ring != null) ring.beginDeal(seed, dealIndex, agents.subList(1, agents.size()).stream().map(Agent::id).toList());
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
