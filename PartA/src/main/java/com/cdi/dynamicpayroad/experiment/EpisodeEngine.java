package com.cdi.dynamicpayroad.experiment;

import com.cdi.dynamicpayroad.domain.Deal;
import com.cdi.dynamicpayroad.domain.DealCommand;
import com.cdi.dynamicpayroad.domain.DealEvent;
import com.cdi.dynamicpayroad.experiment.ActionLog.Action;
import com.cdi.dynamicpayroad.experiment.Agent.ActorType;
import com.cdi.dynamicpayroad.experiment.DealSource.DealRow;
import com.cdi.dynamicpayroad.redis.MarketOutcome;
import com.cdi.dynamicpayroad.redis.RedisMarket;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.SplittableRandom;

/**
 * Runs one deal (one episode) on a fresh virtual clock (plan v6 §3.3, ml-design v5 §6.1).
 *
 * <p>Setup: FLUSHDB → create_deal.lua → presence_upsert.lua for every driver (TTL 1 day).
 * Expiry is driven by sweep.lua, scheduled at the deal's expiresAt and at every posted offer's
 * expiresAt (not once a second). Rules are never judged here: every decision comes back from Lua.
 *
 * <p>Events are delivered in the order the scripts produced them. A command submitted while
 * events are being delivered is applied at once, but its events wait behind the ones already
 * queued, so every agent sees the same order. When the deal is MATCHED/EXPIRED/CANCELLED the
 * queue is cleared and the episode ends.
 */
public final class EpisodeEngine implements EpisodeContext {

    public static final String RIDER_ID = "R-SIM";
    /** Drivers stay present for the whole episode (ml-design v5 §6.1). */
    static final Duration PRESENCE_TTL = Duration.ofDays(1);
    /** Safety bound only; sweep.lua closes every deal at its TTL. */
    static final Duration MAX_EPISODE = Duration.ofDays(1);

    /** What one episode leaves behind for deals_out.csv. */
    public record Result(DealRow row, int dealIndex, List<Agent> agents, Deal deal, Instant createdAt, Instant closedAt) {

        public double durationSec() {
            return Duration.between(createdAt, closedAt).toMillis() / 1000.0;
        }

        public int driverCount() {
            return (int) agents.stream().filter(a -> a.actorType() == ActorType.DRIVER).count();
        }
    }

    private final RedisMarket market;
    private final DealRow row;
    private final List<Agent> agents;
    private final int dealIndex;
    private final ActionLog log;
    private final SplittableRandom rng;
    private final VirtualClock clock = new VirtualClock();
    private final EventQueue queue = new EventQueue(clock);

    private final Deque<DealEvent> pending = new ArrayDeque<>();
    private boolean dispatching;
    private boolean ended;
    private Instant createdAt;
    private Instant closedAt;
    /** Live bids by driver id, kept from events: tells BID_PLACE from BID_UPDATE and prices ACCEPT_BID. */
    private final Map<String, Deal.Bid> liveBids = new LinkedHashMap<>();
    private Double offerPrice;

    public EpisodeEngine(RedisMarket market, DealRow row, List<Agent> agents, long seed, int dealIndex, ActionLog log) {
        this(market, row, agents, episodeRng(seed, dealIndex), dealIndex, log);
    }

    /**
     * For bots that pick the drivers and draw their values before the episode starts: {@code rng}
     * must be {@link #episodeRng}, already advanced by those draws.
     */
    public EpisodeEngine(RedisMarket market, DealRow row, List<Agent> agents, SplittableRandom rng, int dealIndex,
                         ActionLog log) {
        this.market = market;
        this.row = row;
        this.agents = List.copyOf(agents);
        this.dealIndex = dealIndex;
        this.log = log;
        this.rng = rng;
    }

    /** The episode's only source of randomness. */
    public static SplittableRandom episodeRng(long seed, int dealIndex) {
        return new SplittableRandom(seed * 1_000_003L + dealIndex);
    }

    public Result run() {
        market.flushDb();
        createdAt = clock.instant();
        market.createDeal(row.dealId(), RIDER_ID, row.originLat(), row.originLng(), row.basePrice(), Map.of(), createdAt);
        for (Agent a : agents) {
            if (a.actorType() != ActorType.DRIVER) continue;
            double[] at = a.position().orElse(new double[] {row.originLat(), row.originLng()});
            String status = market.upsertPresence("DRIVER", a.id(), at[0], at[1], PRESENCE_TTL, createdAt);
            log.add(row.dealId(), 0, ActorType.DRIVER, a.id(), Action.PRESENT, null, status != null,
                    status == null ? "PRESENCE_REFUSED" : null);
        }
        queue.schedule(deal().expiresAt(), this::sweep);

        for (Agent a : agents) a.onStart(this);
        queue.runUntil(createdAt.plus(MAX_EPISODE));
        if (!ended) throw new IllegalStateException("deal " + row.dealId() + " did not end within " + MAX_EPISODE);

        return new Result(row, dealIndex, agents, deal(), createdAt, closedAt);
    }

    // ---- EpisodeContext ----

    @Override
    public Instant now() {
        return clock.instant();
    }

    @Override
    public double elapsedSec() {
        return Duration.between(createdAt, clock.instant()).toMillis() / 1000.0;
    }

    @Override
    public void schedule(double afterSec, Runnable action) {
        if (ended) return;
        if (!(afterSec >= 0)) throw new IllegalArgumentException("afterSec must be >= 0: " + afterSec);
        queue.schedule(clock.instant().plusMillis(Math.round(afterSec * 1000)), () -> {
            if (!ended) action.run();
        });
    }

    @Override
    public MarketOutcome submit(DealCommand command) {
        Instant now = clock.instant();
        Action action = action(command);
        Double price = price(command);
        MarketOutcome r = market.apply(row.dealId(), command, now);
        String reject = !r.ok() ? r.code().name()
                : r.requesterErrorCode() != null ? r.requesterErrorCode().name() : null;
        log.add(row.dealId(), elapsedSec(), actorType(command), actorId(command), action, price, reject == null, reject);
        handle(r);
        return r;
    }

    @Override
    public Deal deal() {
        return market.snapshot(row.dealId(), clock.instant())
                .orElseThrow(() -> new IllegalStateException("deal vanished: " + row.dealId()))
                .deal();
    }

    @Override
    public DealRow row() {
        return row;
    }

    @Override
    public SplittableRandom rng() {
        return rng;
    }

    // ---- internals ----

    private void sweep() {
        handle(market.sweep(clock.instant()));
    }

    /** Commands and sweeps alike: track state, queue the events, deliver them, end the episode if closed. */
    private void handle(MarketOutcome r) {
        if (!r.ok()) return;
        for (DealEvent e : r.events().getOrDefault(row.dealId(), List.of())) {
            track(e);
            pending.add(e);
        }
        if (r.closed().contains(row.dealId()) && !ended) {
            ended = true;
            closedAt = r.closedAt();
        }
        if (dispatching) return;
        dispatching = true;
        try {
            DealEvent e;
            while ((e = pending.poll()) != null) deliver(e);
        } finally {
            dispatching = false;
        }
        if (ended) queue.clear();
    }

    private void track(DealEvent e) {
        switch (e) {
            case DealEvent.BidPlaced b -> liveBids.put(b.bid().driverId(), b.bid());
            case DealEvent.BidUpdated b -> liveBids.put(b.bid().driverId(), b.bid());
            case DealEvent.BidWithdrawn w -> liveBids.remove(w.driverId());
            case DealEvent.OfferPosted o -> {
                offerPrice = o.price();
                if (!ended) queue.schedule(o.expiresAt(), this::sweep);
            }
            case DealEvent.OfferExpired o -> offerPrice = null;
            case DealEvent.DealMatched m -> offerPrice = null;
            case DealEvent.DealExpired x -> {
                liveBids.clear();
                offerPrice = null;
            }
        }
    }

    private void deliver(DealEvent e) {
        for (Agent a : agents) {
            if (e instanceof DealEvent.OfferPosted o && a.actorType() == ActorType.DRIVER) {
                log.add(row.dealId(), elapsedSec(), ActorType.DRIVER, a.id(), Action.OFFER_SEEN, o.price(), true, null);
            }
            a.onEvent(this, e);
        }
    }

    private Action action(DealCommand c) {
        return switch (c) {
            case DealCommand.PlaceBid b -> liveBids.containsKey(b.driverId()) ? Action.BID_UPDATE : Action.BID_PLACE;
            case DealCommand.WithdrawBid w -> Action.WITHDRAW;
            case DealCommand.PostOffer o -> Action.OFFER_POST;
            case DealCommand.AcceptBid a -> Action.ACCEPT_BID;
            case DealCommand.AcceptOffer a -> Action.ACCEPT_OFFER;
            case DealCommand.Cancel x -> Action.CANCEL;
        };
    }

    private Double price(DealCommand c) {
        return switch (c) {
            case DealCommand.PlaceBid b -> b.price();
            case DealCommand.PostOffer o -> o.price();
            case DealCommand.AcceptOffer a -> offerPrice;
            case DealCommand.AcceptBid a -> liveBids.values().stream()
                    .filter(b -> b.bidId().equals(a.bidId())).map(Deal.Bid::price).findFirst().orElse(null);
            case DealCommand.WithdrawBid w -> null;
            case DealCommand.Cancel x -> null;
        };
    }

    private static ActorType actorType(DealCommand c) {
        return switch (c) {
            case DealCommand.PlaceBid b -> ActorType.DRIVER;
            case DealCommand.WithdrawBid w -> ActorType.DRIVER;
            case DealCommand.AcceptOffer a -> ActorType.DRIVER;
            case DealCommand.PostOffer o -> ActorType.RIDER;
            case DealCommand.AcceptBid a -> ActorType.RIDER;
            case DealCommand.Cancel x -> ActorType.RIDER;
        };
    }

    private static String actorId(DealCommand c) {
        return switch (c) {
            case DealCommand.PlaceBid b -> b.driverId();
            case DealCommand.WithdrawBid w -> w.driverId();
            case DealCommand.AcceptOffer a -> a.driverId();
            case DealCommand.PostOffer o -> o.riderId();
            case DealCommand.AcceptBid a -> a.riderId();
            case DealCommand.Cancel x -> x.riderId();
        };
    }
}
