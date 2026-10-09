package com.cdi.dynamicpayroad.experiment.bots;

import com.cdi.dynamicpayroad.domain.Deal;
import com.cdi.dynamicpayroad.domain.DealCommand;
import com.cdi.dynamicpayroad.domain.DealEvent;
import com.cdi.dynamicpayroad.experiment.Agent;
import com.cdi.dynamicpayroad.experiment.DealSource.DealRow;
import com.cdi.dynamicpayroad.experiment.EpisodeContext;
import com.cdi.dynamicpayroad.experiment.EpisodeEngine;
import com.cdi.dynamicpayroad.redis.MarketOutcome;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.SplittableRandom;

/**
 * The rider bot (ml-design v5 §6.3). {@link #prepare} draws this deal's budget B, time value τ,
 * patience T and aspiration a before the episode starts.
 *
 * <p>Bargain mode: on every bid event and every check interval, take the best bid (lowest
 * price + τ × base_price × pickupEtaMin; ties by price, then the earlier bid) after the accept
 * delay if its price ≤ B and (its cost ≤ a × base_price or T has passed). At the offer times,
 * post min(B, base_price × (0.80 + 0.05 j)) if it is higher than the last offer. Never cancels.
 * Fixed-price mode (E3): offer base_price at t = 0 and cancel once the offer expires.
 */
public final class RiderBot implements Agent {

    /** Uniform draws per deal, always the same count so paired episodes share their randomness. */
    static final int DRAWS = 5;

    private BotParams.Rider p;
    private boolean fixedPrice;
    private double basePrice;
    private double budget;
    private double tau;
    private double patience;
    private double aspiration;
    private double acceptDelay;
    private boolean acceptPending;
    private Double lastOffer;
    private long nextSeq;
    /** Live bids by driver id with the order they arrived, kept from events. */
    private final Map<String, Seen> bids = new LinkedHashMap<>();

    private record Seen(Deal.Bid bid, long seq) {}

    /**
     * @param tauOverride when not null, every rider uses this τ (E5); τ is still drawn so the
     *                    other values do not move
     */
    public void prepare(BotParams params, DealRow row, boolean fixedPrice, Double tauOverride, SplittableRandom rng) {
        double[] x = new double[DRAWS];
        for (int i = 0; i < DRAWS; i++) x[i] = rng.nextDouble();

        this.p = params.rider();
        this.fixedPrice = fixedPrice;
        this.basePrice = row.basePrice();
        budget = row.basePrice() * BotParams.u(p.budget(), x[0]);
        tau = tauOverride != null ? tauOverride : BotParams.u(p.tau(), x[1]);
        patience = BotParams.u(p.patienceS(), x[2]);
        aspiration = BotParams.u(p.aspiration(), x[3]);
        acceptDelay = BotParams.u(p.acceptDelayS(), x[4]);

        acceptPending = false;
        lastOffer = null;
        nextSeq = 0;
        bids.clear();
    }

    @Override public String id() { return EpisodeEngine.RIDER_ID; }
    @Override public ActorType actorType() { return ActorType.RIDER; }

    public double budget() {
        return budget;
    }

    public double tau() {
        return tau;
    }

    @Override
    public void onStart(EpisodeContext ctx) {
        if (fixedPrice) {
            ctx.schedule(0, () -> post(ctx, basePrice));
            return;
        }
        ctx.schedule(p.checkIntervalS(), () -> tick(ctx));
        double[] times = p.offerTimesS();
        for (int j = 0; j < times.length; j++) {
            double price = Math.min(budget, basePrice * (p.offerBase() + p.offerStep() * j));
            ctx.schedule(times[j], () -> offer(ctx, price));
        }
    }

    @Override
    public void onEvent(EpisodeContext ctx, DealEvent e) {
        switch (e) {
            case DealEvent.BidPlaced b -> {
                bids.put(b.bid().driverId(), new Seen(b.bid(), nextSeq++));
                judge(ctx);
            }
            case DealEvent.BidUpdated b -> {
                bids.put(b.bid().driverId(), new Seen(b.bid(), nextSeq++));
                judge(ctx);
            }
            case DealEvent.BidWithdrawn w -> bids.remove(w.driverId());
            case DealEvent.OfferExpired o -> {
                if (fixedPrice) ctx.submit(new DealCommand.Cancel(id()));
            }
            case DealEvent.OfferPosted o -> {}
            case DealEvent.DealMatched m -> {}
            case DealEvent.DealExpired x -> {}
        }
    }

    private void tick(EpisodeContext ctx) {
        judge(ctx);
        ctx.schedule(p.checkIntervalS(), () -> tick(ctx));
    }

    private double cost(Deal.Bid b) {
        return b.price() + tau * basePrice * b.pickupEtaMin();
    }

    /** Picks the best bid and, if it is good enough, accepts it after the accept delay. */
    private void judge(EpisodeContext ctx) {
        if (fixedPrice || acceptPending || bids.isEmpty()) return;
        Seen best = null;
        for (Seen s : bids.values()) {
            if (best == null || better(s, best)) best = s;
        }
        Deal.Bid bid = best.bid();
        if (bid.price() > budget) return;
        if (cost(bid) > aspiration * basePrice && ctx.elapsedSec() < patience) return;

        acceptPending = true;
        String bidId = bid.bidId();
        ctx.schedule(acceptDelay, () -> {
            MarketOutcome r = ctx.submit(new DealCommand.AcceptBid(id(), bidId, null));
            if (!r.ok()) {
                // Usually BID_NOT_FOUND: the driver replaced the bid meanwhile. Look again now.
                acceptPending = false;
                judge(ctx);
            }
        });
    }

    private boolean better(Seen a, Seen b) {
        int c = Double.compare(cost(a.bid()), cost(b.bid()));
        if (c != 0) return c < 0;
        c = Double.compare(a.bid().price(), b.bid().price());
        if (c != 0) return c < 0;
        return a.seq() < b.seq();
    }

    /** Offers only while no accept is on its way, and only above the last offer. */
    private void offer(EpisodeContext ctx, double price) {
        if (acceptPending) return;
        if (lastOffer != null && price <= lastOffer) return;
        post(ctx, price);
    }

    private void post(EpisodeContext ctx, double price) {
        MarketOutcome r = ctx.submit(new DealCommand.PostOffer(id(), price, null));
        if (r.ok() && r.requesterErrorCode() == null) lastOffer = price;
    }
}
