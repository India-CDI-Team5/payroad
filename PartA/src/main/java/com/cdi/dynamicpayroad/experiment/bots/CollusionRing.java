package com.cdi.dynamicpayroad.experiment.bots;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.Set;
import java.util.SplittableRandom;

/**
 * The colluding drivers of one run (ml-design v5 §7.1·§7.2, card D1). The ring is a Java object
 * that lives for the whole run: Redis is flushed every episode, so no collusion state goes there.
 *
 * <p>Before each episode {@link #beginDeal} sees which members were drawn into the deal and gives
 * each one a {@link Role}. "Together" means two or more members in the same deal. A member alone
 * plays its own C1 strategy, except S1 (keeps its floor) and S4 (keeps the late matching rule).
 *
 * <p>The ring draws its own values from a separate stream per (seed, deal index), so the episode's
 * stream — rider and every driver's {@link DriverBot#DRAWS} — is the same as with no ring at all.
 */
public final class CollusionRing {

    /** Relative to PartA/, the runner's working directory. */
    public static final Path DEFAULT_PATH = Path.of("../data/experiment/collusion-params.json");
    /** Salt of the ring's shuffle: {@code new Random(seed + 777)}. */
    public static final long RING_SALT = 777;

    /** What a member does in the current deal. */
    public enum Role {
        /** Plays its own C1 strategy (S2/S3 member alone in the deal). */
        BASE,
        /** Floor max(floor, 1.25 × base_price); with others, never under a fellow member's live bid. */
        S1,
        /** S2 designated winner: own strategy with floor × 1.15. */
        S2_WINNER,
        /** S2 cover: bids winner × U(1.05, 1.15) within 2 s of the winner, withdraws at 150 s or on an offer. */
        S2_COVER,
        /** S3 member whose turn it is: competes with its own strategy. */
        S3_COMPETE,
        /** S3 member sitting the deal out. */
        S3_ABSTAIN,
        /** S3 member bidding base_price × U(1.8, 2.2) once and never conceding. */
        S3_HIGH,
        /** S4: waits for an honest bid, then matches the lowest honest bid inside a shared 3 s window. */
        S4
    }

    /** {@code data/experiment/collusion-params.json}; keys fixed by card D1. */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Params(
            @JsonProperty("pool_size") int poolSize,
            @JsonProperty("n_per_deal") int nPerDeal,
            @JsonProperty("deals_per_run") int dealsPerRun,
            Train train,
            @JsonProperty("holdout_S4") Grid holdoutS4,
            @JsonProperty("blind_S5") Grid blindS5,
            @JsonProperty("S1") S1 s1,
            @JsonProperty("S2") S2 s2,
            @JsonProperty("S3") S3 s3,
            @JsonProperty("S4") S4 s4) {

        @JsonIgnoreProperties(ignoreUnknown = true)
        public record Train(List<String> strategies, @JsonProperty("ring_shares") List<Double> ringShares,
                            List<Long> seeds) {}

        @JsonIgnoreProperties(ignoreUnknown = true)
        public record Grid(@JsonProperty("ring_shares") List<Double> ringShares, List<Long> seeds) {}

        @JsonIgnoreProperties(ignoreUnknown = true)
        public record S1(@JsonProperty("floor_mult") double floorMult) {}

        @JsonIgnoreProperties(ignoreUnknown = true)
        public record S2(@JsonProperty("winner_floor_mult") double winnerFloorMult,
                         @JsonProperty("cover_mult") double[] coverMult,
                         @JsonProperty("cover_delay_s") double coverDelayS,
                         @JsonProperty("withdraw_at_s") double withdrawAtS) {}

        @JsonIgnoreProperties(ignoreUnknown = true)
        public record S3(@JsonProperty("abstain_prob") double abstainProb, @JsonProperty("high_bid") double[] highBid) {}

        @JsonIgnoreProperties(ignoreUnknown = true)
        public record S4(@JsonProperty("wait_after_honest_s") double[] waitAfterHonestS,
                         @JsonProperty("entry_window_s") double entryWindowS) {}

        public static Params read(Path path) {
            Params p;
            try {
                p = new ObjectMapper().readValue(path.toFile(), Params.class);
            } catch (IOException e) {
                throw new UncheckedIOException("cannot read collusion params: " + path, e);
            }
            p.check(path);
            return p;
        }

        /** Default ring shares and seeds of a strategy: train for S1~S3, holdout_S4 for S4. */
        public Grid grid(CollusionStrategy s) {
            return s == CollusionStrategy.S4 ? holdoutS4 : new Grid(train.ringShares(), train.seeds());
        }

        private void check(Path path) {
            List<String> bad = new ArrayList<>();
            if (train == null || holdoutS4 == null || s1 == null || s2 == null || s3 == null || s4 == null) {
                throw new IllegalArgumentException(path + ": train, holdout_S4 and S1~S4 are required");
            }
            if (poolSize <= 0) bad.add("pool_size");
            if (nPerDeal <= 0 || nPerDeal > poolSize) bad.add("n_per_deal");
            if (dealsPerRun <= 0) bad.add("deals_per_run");
            for (Grid g : List.of(new Grid(train.ringShares(), train.seeds()), holdoutS4)) {
                if (g.seeds() == null || g.seeds().size() != 2 || g.seeds().get(0) > g.seeds().get(1)) bad.add("seeds");
                if (g.ringShares() == null || g.ringShares().stream().anyMatch(x -> x < 0 || x > 1)) bad.add("ring_shares");
            }
            pair(bad, "S2.cover_mult", s2.coverMult());
            pair(bad, "S3.high_bid", s3.highBid());
            pair(bad, "S4.wait_after_honest_s", s4.waitAfterHonestS());
            if (!(s2.coverDelayS() >= 0) || !(s4.entryWindowS() >= 0)) bad.add("delays");
            if (!(s3.abstainProb() >= 0 && s3.abstainProb() <= 1)) bad.add("S3.abstain_prob");
            if (!bad.isEmpty()) throw new IllegalArgumentException(path + ": bad values " + bad);
        }

        private static void pair(List<String> bad, String name, double[] r) {
            if (r == null || r.length != 2 || r[0] > r[1]) bad.add(name);
        }
    }

    private final CollusionStrategy strategy;
    private final Params params;
    /** Member ids in id order. */
    private final Set<String> members;

    // S3: whose turn it is, kept across the run
    private int turn;

    // current deal
    private int dealIndex;
    private List<String> present = List.of();
    private final Map<String, Role> roles = new HashMap<>();
    private String s2Winner;
    private final Map<String, Double> coverShare = new HashMap<>();
    private final Map<String, Double> coverDelay = new HashMap<>();
    private final Map<String, Double> highShare = new HashMap<>();
    private double s4Wait;
    private final Map<String, Double> s4Offset = new HashMap<>();

    private CollusionRing(CollusionStrategy strategy, Params params, Set<String> members) {
        this.strategy = strategy;
        this.params = params;
        this.members = Collections.unmodifiableSet(members);
    }

    /**
     * The ring of one run: the pool shuffled by {@code new Random(seed + 777)}, the first
     * round(share × pool size) drivers. Every member joins the ring ({@link DriverBot#joinRing}).
     */
    public static CollusionRing form(CollusionStrategy strategy, Params params, List<DriverBot> pool, double share,
                                     long seed) {
        List<DriverBot> order = new ArrayList<>(pool);
        order.sort((a, b) -> a.id().compareTo(b.id()));
        Collections.shuffle(order, new Random(seed + RING_SALT));
        int size = (int) Math.round(share * pool.size());
        List<DriverBot> chosen = order.subList(0, size);
        Set<String> ids = new LinkedHashSet<>();
        chosen.stream().map(DriverBot::id).sorted().forEach(ids::add);
        CollusionRing ring = new CollusionRing(strategy, params, ids);
        for (DriverBot d : chosen) d.joinRing(ring);
        return ring;
    }

    /** The ring's own stream for one deal, apart from {@code EpisodeEngine.episodeRng}. */
    static SplittableRandom dealRng(long seed, int dealIndex) {
        return new SplittableRandom((seed * 1_000_003L + dealIndex) ^ 0x9E3779B97F4A7C15L);
    }

    /**
     * Assigns this deal's roles. {@code drawn} are the deal's drivers; the members among them, in
     * id order, are "present". All draws happen here, in a fixed order, from {@link #dealRng}.
     */
    public void beginDeal(long seed, int dealIndex, List<String> drawn) {
        this.dealIndex = dealIndex;
        present = drawn.stream().filter(members::contains).sorted().toList();
        roles.clear();
        coverShare.clear();
        coverDelay.clear();
        highShare.clear();
        s4Offset.clear();
        s2Winner = null;
        SplittableRandom rng = dealRng(seed, dealIndex);
        boolean together = together();
        switch (strategy) {
            case S1 -> present.forEach(id -> roles.put(id, Role.S1));
            case S2 -> {
                if (!together) {
                    present.forEach(id -> roles.put(id, Role.BASE));
                    break;
                }
                s2Winner = present.get(dealIndex % present.size());
                for (String id : present) {
                    double share = BotParams.u(params.s2().coverMult(), rng.nextDouble());
                    double delay = params.s2().coverDelayS() * rng.nextDouble();
                    if (id.equals(s2Winner)) {
                        roles.put(id, Role.S2_WINNER);
                    } else {
                        roles.put(id, Role.S2_COVER);
                        coverShare.put(id, share);
                        coverDelay.put(id, delay);
                    }
                }
            }
            case S3 -> {
                if (!together) {
                    present.forEach(id -> roles.put(id, Role.BASE));
                    break;
                }
                String competitor = present.get(turn % present.size());
                for (String id : present) {
                    double abstain = rng.nextDouble();
                    double high = BotParams.u(params.s3().highBid(), rng.nextDouble());
                    if (id.equals(competitor)) {
                        roles.put(id, Role.S3_COMPETE);
                    } else if (abstain < params.s3().abstainProb()) {
                        roles.put(id, Role.S3_ABSTAIN);
                    } else {
                        roles.put(id, Role.S3_HIGH);
                        highShare.put(id, high);
                    }
                }
            }
            case S4 -> {
                s4Wait = BotParams.u(params.s4().waitAfterHonestS(), rng.nextDouble());
                for (String id : present) {
                    roles.put(id, Role.S4);
                    s4Offset.put(id, params.s4().entryWindowS() * rng.nextDouble());
                }
            }
        }
    }

    /** After the episode: S3 passes the turn on when the members met. */
    public void endDeal() {
        if (strategy == CollusionStrategy.S3 && together()) turn++;
    }

    public CollusionStrategy strategy() {
        return strategy;
    }

    public Params params() {
        return params;
    }

    public Set<String> members() {
        return members;
    }

    public boolean isMember(String driverId) {
        return members.contains(driverId);
    }

    /** Members drawn into the current deal, in id order. */
    public List<String> present() {
        return present;
    }

    public boolean together() {
        return present.size() >= 2;
    }

    public int dealIndex() {
        return dealIndex;
    }

    /** This deal's role of a member; null for a driver outside the ring or not in the deal. */
    public Role role(String driverId) {
        return roles.get(driverId);
    }

    /** S3's turn counter: how many deals the members met in so far. */
    public int turn() {
        return turn;
    }

    /** S2: the designated winner of the current deal, null when the members did not meet. */
    public String s2Winner() {
        return s2Winner;
    }

    /** S2: this cover's bid as a share of the winner's live bid. */
    double coverShare(String driverId) {
        return coverShare.get(driverId);
    }

    /** S2: seconds after the winner's first bid at which this cover bids. */
    double coverDelay(String driverId) {
        return coverDelay.get(driverId);
    }

    /** S3: this member's one high bid as a share of base_price. */
    double highShare(String driverId) {
        return highShare.get(driverId);
    }

    /** S4: seconds from the first honest bid to this member's entry (shared wait + own offset in the window). */
    double s4EntryAfterHonest(String driverId) {
        return s4Wait + s4Offset.get(driverId);
    }

    /** Highest live bid of the other present members, or null when none has one. */
    Double highestOtherMemberBid(String self, Map<String, Double> liveBids) {
        Double best = null;
        for (String id : present) {
            if (id.equals(self)) continue;
            Double b = liveBids.get(id);
            if (b != null && (best == null || b > best)) best = b;
        }
        return best;
    }

    /** Lowest live bid of a driver outside the ring, or null when there is none. */
    Double lowestHonestBid(Map<String, Double> liveBids) {
        Double best = null;
        for (Map.Entry<String, Double> e : liveBids.entrySet()) {
            if (members.contains(e.getKey())) continue;
            if (best == null || e.getValue() < best) best = e.getValue();
        }
        return best;
    }
}
