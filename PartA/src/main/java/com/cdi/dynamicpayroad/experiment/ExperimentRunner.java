package com.cdi.dynamicpayroad.experiment;

import com.cdi.dynamicpayroad.domain.Deal;
import com.cdi.dynamicpayroad.domain.DealCommand;
import com.cdi.dynamicpayroad.domain.DealEvent;
import com.cdi.dynamicpayroad.experiment.DealSource.DealRow;
import com.cdi.dynamicpayroad.redis.RedisMarket;
import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisURI;
import io.lettuce.core.api.StatefulRedisConnection;

import java.util.List;
import java.util.Locale;

/**
 * Experiment runner entry point (plan v6 §3.3): no Spring, one thread, virtual time, the live
 * service's Lua rules on Redis DB 14. Run with
 * {@code ./gradlew runExperiment --args="--scenario smoke --seed 1"}.
 *
 * <p>Only the {@code smoke} scenario exists so far (card C1): one dummy driver bids base_price
 * at t = 5 s and the dummy rider accepts at t = 7 s.
 */
public final class ExperimentRunner {

    static final int SMOKE_DEALS = 10;
    static final String SMOKE_DRIVER_ID = "D-0001";

    /** What main prints at the end. Wall time goes to stdout only, never into a CSV. */
    public record RunSummary(int episodes, double wallMsPerEpisode) {}

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
        if (!cfg.scenario().equals("smoke")) {
            throw new IllegalArgumentException("not implemented (C2~C5, D1): " + cfg.scenario());
        }
        DealSource source = DealSource.read(cfg.deals());

        RedisURI uri = RedisURI.create(cfg.redisUrl());
        RedisClient client = RedisClient.create(uri);
        try (StatefulRedisConnection<String, String> conn = client.connect();
             CsvExporter csv = new CsvExporter(cfg.rawOut())) {
            RedisMarket market = new RedisMarket(conn.sync(), uri.getDatabase(), cfg.rules());
            return smoke(cfg, source, market, csv);
        } finally {
            client.shutdown();
        }
    }

    private static RunSummary smoke(ScenarioConfig cfg, DealSource source, RedisMarket market, CsvExporter csv) {
        int perRun = cfg.dealsPerRun() == null ? SMOKE_DEALS : cfg.dealsPerRun();
        int episodes = 0;
        long nanos = 0;
        for (long seed : cfg.seeds()) {
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
