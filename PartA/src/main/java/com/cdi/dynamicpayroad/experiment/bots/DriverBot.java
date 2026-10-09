package com.cdi.dynamicpayroad.experiment.bots;

import com.cdi.dynamicpayroad.domain.DealCommand;
import com.cdi.dynamicpayroad.domain.DealEvent;
import com.cdi.dynamicpayroad.experiment.Agent;
import com.cdi.dynamicpayroad.experiment.DealSource.DealRow;
import com.cdi.dynamicpayroad.experiment.EpisodeContext;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Random;
import java.util.SplittableRandom;

/**
 * An honest driver bot (ml-design v5 §6.2). The object lives in the run's driver pool across
 * episodes; {@link #prepare} draws this deal's values before the episode starts.
 *
 * <p>Bargain mode: enter after the entry delay with the strategy's first bid, then every interval
 * concede by the step unless this driver holds the lowest bid, never below the floor; take the
 * rider's offer when it reaches floor × (1 + m). Fixed-price mode (E3): at entry, take the rider's
 * base_price offer if base_price ≥ floor × (1 + m); no bids.
 *
 * <p>Rules are never judged here: a command that breaks one comes back rejected from Lua.
 */
public final class DriverBot implements Agent {

    /** Uniform draws per driver and deal, always the same count so paired episodes share their randomness. */
    static final int DRAWS = 9;

    private final String id;
    private final DriverStrategy strategy;

    // per episode
    private BotParams.Driver p;
    private boolean fixedPrice;
    private double basePrice;
    private double bandMax;
    private double[] position;
    private double pickupKm;
    private double entryDelay;
    private double cost;
    private double floor;
    private double margin;
    private double firstDraw;
    private double stepDraw;
    private double interval;
    private double acceptDelay;
    private boolean entered;
    private boolean acceptScheduled;
    private Double offer;
    /** Live bid price by driver id, this driver included, kept from events. */
    private final Map<String, Double> bids = new HashMap<>();

    public DriverBot(String id, DriverStrategy strategy) {
        this.id = id;
        this.strategy = strategy;
    }

    /**
     * The run's pool: ids D-0001..D-{size}, strategies dealt in the order {@code new Random(seed)}
     * shuffles the ids, round(share × size) each, the last strategy taking what is left.
     * Returned in id order.
     */
    public static List<DriverBot> pool(BotParams params, String config, long seed) {
        int size = params.poolSize();
        List<Double> shares = params.shares(config);
        DriverStrategy[] all = DriverStrategy.values();
        List<String> ids = new ArrayList<>(size);
        for (int i = 1; i <= size; i++) ids.add(String.format("D-%04d", i));
        List<String> order = new ArrayList<>(ids);
        Collections.shuffle(order, new Random(seed));

        Map<String, DriverStrategy> assigned = new HashMap<>();
        int k = 0;
        for (int s = 0; s < all.length; s++) {
            int count = s == all.length - 1 ? size - k : (int) Math.round(shares.get(s) * size);
            for (int j = 0; j < count && k < size; j++) assigned.put(order.get(k++), all[s]);
        }
        List<DriverBot> pool = new ArrayList<>(size);
        for (String i : ids) pool.add(new DriverBot(i, assigned.get(i)));
        return pool;
    }

    /** Draws this deal's values ({@link #DRAWS} uniforms, in a fixed order) and resets the episode state. */
    public void prepare(BotParams params, DealRow row, double bandMinRatio, double bandMaxRatio, boolean fixedPrice,
                        SplittableRandom rng) {
        double[] x = new double[DRAWS];
        for (int i = 0; i < DRAWS; i++) x[i] = rng.nextDouble();

        this.p = params.driver();
        this.fixedPrice = fixedPrice;
        this.basePrice = row.basePrice();
        this.bandMax = bandMaxRatio * row.basePrice();
        pickupKm = BotParams.u(p.pickupKm(), x[0]);
        double theta = 2 * Math.PI * x[1];
        double lat = row.originLat() + pickupKm / 111.0 * Math.cos(theta);
        double lng = row.originLng() + pickupKm / (111.0 * Math.cos(row.originLat() * Math.PI / 180)) * Math.sin(theta);
        position = new double[] {lat, lng};
        entryDelay = BotParams.u(p.entryDelayS(), x[2]);
        // Cost is set by base_dry, not by the weather (ml-design v5 §6.2).
        cost = row.baseDry() * BotParams.u(p.costFactor(), x[3]) * (1 + p.costPerKm() * pickupKm);
        // Same product as create_deal.lua's bandMin, so a bid at the floor is never OUT_OF_BAND.
        floor = Math.max(cost, row.basePrice() * bandMinRatio);
        margin = BotParams.u(p.acceptMargin(), x[4]);
        firstDraw = x[5];
        stepDraw = x[6];
        interval = switch (strategy) {
            case AGG -> BotParams.u(p.agg().intervalS(), x[7]);
            case CON -> BotParams.u(p.con().intervalS(), x[7]);
            case DIST -> BotParams.u(p.dist().intervalS(), x[7]);
            case OPP -> BotParams.u(p.opp().intervalS(), x[7]);
        };
        acceptDelay = BotParams.u(p.acceptDelayS(), x[8]);

        entered = false;
        acceptScheduled = false;
        offer = null;
        bids.clear();
    }

    @Override public String id() { return id; }
    @Override public ActorType actorType() { return ActorType.DRIVER; }
    @Override public String strategy() { return strategy.name(); }

    public DriverStrategy driverStrategy() {
        return strategy;
    }

    @Override
    public Optional<double[]> position() {
        return Optional.of(position.clone());
    }

    public double floor() {
        return floor;
    }

    public double margin() {
        return margin;
    }

    @Override
    public void onStart(EpisodeContext ctx) {
        ctx.schedule(entryDelay, () -> enter(ctx));
    }

    @Override
    public void onEvent(EpisodeContext ctx, DealEvent e) {
        switch (e) {
            case DealEvent.BidPlaced b -> bids.put(b.bid().driverId(), b.bid().price());
            case DealEvent.BidUpdated b -> bids.put(b.bid().driverId(), b.bid().price());
            case DealEvent.BidWithdrawn w -> bids.remove(w.driverId());
            case DealEvent.OfferPosted o -> {
                offer = o.price();
                if (!fixedPrice) considerOffer(ctx);
            }
            case DealEvent.OfferExpired o -> offer = null;
            case DealEvent.DealMatched m -> {}
            case DealEvent.DealExpired x -> {}
        }
    }

    private void enter(EpisodeContext ctx) {
        entered = true;
        if (fixedPrice) {
            if (offer != null && basePrice >= floor * (1 + margin)) ctx.submit(new DealCommand.AcceptOffer(id, null));
            return;
        }
        ctx.submit(new DealCommand.PlaceBid(id, firstBid(), position[0], position[1], null));
        considerOffer(ctx);
        ctx.schedule(interval, () -> concede(ctx));
    }

    /** The strategy's first bid, cut to the band and never below the floor. */
    double firstBid() {
        double share = switch (strategy) {
            case AGG -> BotParams.u(p.agg().first(), firstDraw);
            case CON -> BotParams.u(p.con().first(), firstDraw);
            case DIST -> Math.min(p.dist().firstBase() + p.dist().firstPerKm() * pickupKm, 3.0);
            case OPP -> {
                int bidders = bids.size();
                yield bidders <= 1 ? p.opp().firstLe1() : bidders <= 3 ? p.opp().firstLe3() : p.opp().firstElse();
            }
        };
        return Math.min(Math.max(share * basePrice, floor), bandMax);
    }

    private double step() {
        double share = switch (strategy) {
            case AGG -> BotParams.u(p.agg().step(), stepDraw);
            case CON -> BotParams.u(p.con().step(), stepDraw);
            case DIST -> p.dist().step();
            case OPP -> p.opp().stepPerBidder() * Math.max(1, bids.size());
        };
        return share * basePrice;
    }

    /** One step down unless this driver holds the lowest bid; stops for good at the floor. */
    private void concede(EpisodeContext ctx) {
        Double mine = bids.get(id);
        if (mine == null || mine <= floor) return;
        if (!holdsLowest(mine)) {
            ctx.submit(new DealCommand.PlaceBid(id, Math.max(mine - step(), floor), position[0], position[1], null));
        }
        ctx.schedule(interval, () -> concede(ctx));
    }

    /** No other live bid is cheaper (a tie counts as lowest). */
    private boolean holdsLowest(double mine) {
        for (Map.Entry<String, Double> b : bids.entrySet()) {
            if (!b.getKey().equals(id) && b.getValue() < mine) return false;
        }
        return true;
    }

    private void considerOffer(EpisodeContext ctx) {
        if (!entered || acceptScheduled || offer == null || offer < floor * (1 + margin)) return;
        acceptScheduled = true;
        ctx.schedule(acceptDelay, () -> {
            acceptScheduled = false;
            if (offer != null) ctx.submit(new DealCommand.AcceptOffer(id, null));
        });
    }
}
