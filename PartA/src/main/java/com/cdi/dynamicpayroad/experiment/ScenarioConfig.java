package com.cdi.dynamicpayroad.experiment;

import com.cdi.dynamicpayroad.domain.DealRules;
import io.lettuce.core.RedisURI;

import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * Command-line arguments of the experiment runner (card C1). Unknown or malformed arguments
 * throw {@link IllegalArgumentException}; {@link ExperimentRunner#main} turns that into an exit code.
 * Optional values the scenario decides are left null.
 */
public record ScenarioConfig(
        String scenario,
        Path deals,
        List<Long> seeds,
        String config,
        Integer n,
        Integer dealsPerRun,
        Path out,
        Path rawOut,
        Integer offerTtlSec,
        Integer roundLimit,
        Double tau,
        boolean betaOff,
        List<Double> ringShares,
        String strategy,
        String redisUrl) {

    public static final String DEFAULT_REDIS_URL = "redis://localhost:6379/14";
    public static final long DEFAULT_SEED = 42;
    private static final Set<String> CONFIGS = Set.of("C1", "C2", "C3", "C4");
    private static final Set<String> STRATEGIES = Set.of("S1", "S2", "S3", "S4", "S5");

    public static ScenarioConfig parse(String... args) {
        String scenario = null, config = null, strategy = null, redisUrl = DEFAULT_REDIS_URL;
        Path deals = DealSource.DEFAULT_PATH, out = null, rawOut = null;
        Long seed = null;
        List<Long> seeds = null;
        Integer n = null, dealsPerRun = null, offerTtl = null, roundLimit = null;
        Double tau = null;
        boolean betaOff = false;
        List<Double> ringShares = null;

        for (int i = 0; i < args.length; i++) {
            String a = args[i];
            switch (a) {
                case "--beta-off" -> betaOff = true;
                case "--scenario" -> scenario = value(args, ++i, a);
                case "--deals" -> deals = Path.of(value(args, ++i, a));
                case "--seed" -> seed = parseLong(value(args, ++i, a), a);
                case "--seeds" -> seeds = range(value(args, ++i, a));
                case "--config" -> {
                    config = value(args, ++i, a);
                    if (!CONFIGS.contains(config)) throw new IllegalArgumentException("--config must be C1..C4: " + config);
                }
                case "--n" -> n = positive(value(args, ++i, a), a);
                case "--deals-per-run" -> dealsPerRun = positive(value(args, ++i, a), a);
                case "--out" -> out = Path.of(value(args, ++i, a));
                case "--raw-out" -> rawOut = Path.of(value(args, ++i, a));
                case "--offer-ttl" -> offerTtl = positive(value(args, ++i, a), a);
                case "--round-limit" -> roundLimit = positive(value(args, ++i, a), a);
                case "--tau" -> tau = parseDouble(value(args, ++i, a), a);
                case "--ring-shares" -> {
                    ringShares = new ArrayList<>();
                    for (String s : value(args, ++i, a).split(",")) ringShares.add(parseDouble(s.trim(), a));
                }
                case "--strategy" -> {
                    strategy = value(args, ++i, a);
                    if (!STRATEGIES.contains(strategy)) throw new IllegalArgumentException("--strategy must be S1..S5: " + strategy);
                }
                case "--redis-url" -> redisUrl = value(args, ++i, a);
                default -> throw new IllegalArgumentException("unknown argument: " + a);
            }
        }

        if (scenario == null || scenario.isBlank()) throw new IllegalArgumentException("--scenario is required");
        if (seed != null && seeds != null) throw new IllegalArgumentException("give --seed or --seeds, not both");
        if (seeds == null && seed != null) seeds = List.of(seed);
        if (out == null) out = Path.of("../results/sim", scenario);
        if (rawOut == null) rawOut = Path.of("../results/sim/raw", scenario);

        RedisURI uri;
        try {
            uri = RedisURI.create(redisUrl);
        } catch (RuntimeException e) {
            throw new IllegalArgumentException("bad --redis-url: " + redisUrl, e);
        }
        if (uri.getDatabase() == 0) throw new IllegalArgumentException("DB 0(실서비스)에서는 실행하지 않습니다: " + redisUrl);

        return new ScenarioConfig(scenario, deals, seeds == null ? null : List.copyOf(seeds), config, n, dealsPerRun,
                out, rawOut, offerTtl, roundLimit, tau, betaOff, ringShares == null ? null : List.copyOf(ringShares), strategy,
                redisUrl);
    }

    /** --seed / --seeds, or {@code fallback} when neither was given (the scenario decides). */
    public List<Long> seedsOr(List<Long> fallback) {
        return seeds != null ? seeds : fallback;
    }

    /** DealRules.defaults() with --offer-ttl / --round-limit applied (E4). */
    public DealRules rules() {
        DealRules d = DealRules.defaults();
        return new DealRules(d.bandMinRatio(), d.bandMaxRatio(), d.dealTtl(),
                offerTtlSec == null ? d.offerTtl() : Duration.ofSeconds(offerTtlSec),
                roundLimit == null ? d.roundLimit() : roundLimit,
                d.avgSpeedKmh(), d.detourFactor(), d.maxActiveBids(), d.presenceTtl());
    }

    private static String value(String[] args, int i, String name) {
        if (i >= args.length || args[i].startsWith("--")) throw new IllegalArgumentException(name + " needs a value");
        return args[i];
    }

    /** "a-b", inclusive. */
    private static List<Long> range(String s) {
        String[] p = s.split("-");
        if (p.length != 2) throw new IllegalArgumentException("--seeds must be a-b: " + s);
        long lo = parseLong(p[0].trim(), "--seeds"), hi = parseLong(p[1].trim(), "--seeds");
        if (lo > hi) throw new IllegalArgumentException("--seeds must be a-b with a <= b: " + s);
        List<Long> out = new ArrayList<>();
        for (long x = lo; x <= hi; x++) out.add(x);
        return out;
    }

    private static long parseLong(String s, String name) {
        try {
            return Long.parseLong(s);
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException(name + " is not an integer: " + s);
        }
    }

    private static int positive(String s, String name) {
        long v = parseLong(s, name);
        if (v <= 0 || v > Integer.MAX_VALUE) throw new IllegalArgumentException(name + " must be a positive integer: " + s);
        return (int) v;
    }

    private static double parseDouble(String s, String name) {
        try {
            double v = Double.parseDouble(s);
            if (!Double.isFinite(v)) throw new NumberFormatException();
            return v;
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException(name + " is not a number: " + s);
        }
    }
}
