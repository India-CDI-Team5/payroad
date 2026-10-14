package com.cdi.dynamicpayroad.experiment.bots;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * {@code data/experiment/bot-params.json} (ml-design v5 §6.2~§6.4, card C2). Every bot value comes
 * from this one file; it is frozen in card C3. A pair {@code [a, b]} is the uniform range U(a, b).
 * Unknown keys are ignored: C3 adds {@code frozen_utc} and {@code diag_failed}.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record BotParams(
        int version,
        @JsonProperty("revision_note") String revisionNote,
        @JsonProperty("pool_size") int poolSize,
        @JsonProperty("deals_per_run") int dealsPerRun,
        @JsonProperty("default_n") int defaultN,
        /** First and last seed, inclusive. */
        List<Long> seeds,
        Driver driver,
        Rider rider,
        /** Config name to strategy shares in {@link DriverStrategy} order (AGG, CON, DIST, OPP). */
        Map<String, List<Double>> configs,
        Sweeps sweeps) {

    /** Relative to PartA/, the runner's working directory. */
    public static final Path DEFAULT_PATH = Path.of("../data/experiment/bot-params.json");

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Driver(
            @JsonProperty("pickup_km") double[] pickupKm,
            @JsonProperty("entry_delay_s") double[] entryDelayS,
            @JsonProperty("cost_factor") double[] costFactor,
            @JsonProperty("cost_per_km") double costPerKm,
            @JsonProperty("accept_margin") double[] acceptMargin,
            @JsonProperty("accept_delay_s") double[] acceptDelayS,
            @JsonProperty("AGG") Ranged agg,
            @JsonProperty("CON") Ranged con,
            @JsonProperty("DIST") Dist dist,
            @JsonProperty("OPP") Opp opp) {}

    /** AGG and CON: first bid and step as shares of base_price, step interval in seconds. */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Ranged(double[] first, double[] step, @JsonProperty("interval_s") double[] intervalS) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Dist(@JsonProperty("first_base") double firstBase, @JsonProperty("first_per_km") double firstPerKm,
                       double step, @JsonProperty("interval_s") double[] intervalS) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Opp(@JsonProperty("first_le1") double firstLe1, @JsonProperty("first_le3") double firstLe3,
                      @JsonProperty("first_else") double firstElse,
                      @JsonProperty("step_per_bidder") double stepPerBidder,
                      @JsonProperty("interval_s") double[] intervalS) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Rider(
            double[] budget,
            double[] tau,
            @JsonProperty("patience_s") double[] patienceS,
            double[] aspiration,
            @JsonProperty("check_interval_s") double checkIntervalS,
            @JsonProperty("accept_delay_s") double[] acceptDelayS,
            @JsonProperty("offer_times_s") double[] offerTimesS,
            @JsonProperty("offer_base") double offerBase,
            @JsonProperty("offer_step") double offerStep) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Sweeps(
            @JsonProperty("E1_n") List<Integer> e1N,
            @JsonProperty("E4_offer_ttl") List<Integer> e4OfferTtl,
            @JsonProperty("E4_round_limit") List<Integer> e4RoundLimit,
            @JsonProperty("E4_configs") List<String> e4Configs,
            @JsonProperty("E5_tau") List<Double> e5Tau) {}

    public static BotParams read(Path path) {
        BotParams p;
        try {
            p = new ObjectMapper().readValue(path.toFile(), BotParams.class);
        } catch (IOException e) {
            throw new UncheckedIOException("cannot read bot params: " + path, e);
        }
        p.check(path);
        return p;
    }

    /**
     * The same parameters with only {@code rider.offer_base} replaced, for the post-hoc first-offer
     * sensitivity run (paper-revision-v1 X3). The frozen file itself is never rewritten.
     */
    public BotParams withOfferBase(double offerBase) {
        if (!(offerBase >= 0.7 && offerBase <= 1.5)) {
            throw new IllegalArgumentException("offer_base must be in [0.7, 1.5]: " + offerBase);
        }
        Rider r = rider;
        Rider r2 = new Rider(r.budget(), r.tau(), r.patienceS(), r.aspiration(), r.checkIntervalS(), r.acceptDelayS(),
                r.offerTimesS(), offerBase, r.offerStep());
        return new BotParams(version, revisionNote, poolSize, dealsPerRun, defaultN, seeds, driver, r2, configs, sweeps);
    }

    /** U(r[0], r[1]) from a uniform draw {@code x} in [0, 1). */
    public static double u(double[] r, double x) {
        return r[0] + (r[1] - r[0]) * x;
    }

    /** seeds[0]..seeds[1], inclusive. */
    public List<Long> seedList() {
        List<Long> out = new ArrayList<>();
        for (long s = seeds.get(0); s <= seeds.get(1); s++) out.add(s);
        return out;
    }

    public List<Double> shares(String config) {
        List<Double> s = configs.get(config);
        if (s == null) throw new IllegalArgumentException("bot-params.json has no config " + config);
        return s;
    }

    private void check(Path path) {
        List<String> bad = new ArrayList<>();
        if (driver == null || rider == null || configs == null || sweeps == null || seeds == null) {
            throw new IllegalArgumentException(path + ": driver, rider, configs, sweeps and seeds are required");
        }
        if (seeds.size() != 2 || seeds.get(0) > seeds.get(1)) bad.add("seeds");
        if (poolSize <= 0) bad.add("pool_size");
        if (dealsPerRun <= 0) bad.add("deals_per_run");
        if (defaultN <= 0 || defaultN > poolSize) bad.add("default_n");
        pair(bad, "driver.pickup_km", driver.pickupKm());
        pair(bad, "driver.entry_delay_s", driver.entryDelayS());
        pair(bad, "driver.cost_factor", driver.costFactor());
        pair(bad, "driver.accept_margin", driver.acceptMargin());
        pair(bad, "driver.accept_delay_s", driver.acceptDelayS());
        for (var e : Map.of("AGG", driver.agg(), "CON", driver.con()).entrySet()) {
            if (e.getValue() == null) {
                bad.add("driver." + e.getKey());
                continue;
            }
            pair(bad, "driver." + e.getKey() + ".first", e.getValue().first());
            pair(bad, "driver." + e.getKey() + ".step", e.getValue().step());
            pair(bad, "driver." + e.getKey() + ".interval_s", e.getValue().intervalS());
        }
        if (driver.dist() == null) bad.add("driver.DIST");
        else pair(bad, "driver.DIST.interval_s", driver.dist().intervalS());
        if (driver.opp() == null) bad.add("driver.OPP");
        else pair(bad, "driver.OPP.interval_s", driver.opp().intervalS());
        pair(bad, "rider.budget", rider.budget());
        pair(bad, "rider.tau", rider.tau());
        pair(bad, "rider.patience_s", rider.patienceS());
        pair(bad, "rider.aspiration", rider.aspiration());
        pair(bad, "rider.accept_delay_s", rider.acceptDelayS());
        if (!(rider.checkIntervalS() > 0)) bad.add("rider.check_interval_s");
        if (rider.offerTimesS() == null) bad.add("rider.offer_times_s");
        for (var e : configs.entrySet()) {
            List<Double> s = e.getValue();
            if (s == null || s.size() != DriverStrategy.values().length
                    || Math.abs(s.stream().mapToDouble(Double::doubleValue).sum() - 1.0) > 1e-9) {
                bad.add("configs." + e.getKey());
            }
        }
        for (String c : sweeps.e4Configs()) if (!configs.containsKey(c)) bad.add("sweeps.E4_configs " + c);
        for (int n : sweeps.e1N()) if (n <= 0 || n > poolSize) bad.add("sweeps.E1_n " + n);
        if (!bad.isEmpty()) throw new IllegalArgumentException(path + ": bad values " + bad);
    }

    private static void pair(List<String> bad, String name, double[] r) {
        if (r == null || r.length != 2 || r[0] > r[1]) bad.add(name);
    }
}
