package com.cdi.dynamicpayroad.experiment;

import com.cdi.dynamicpayroad.domain.Deal;
import com.cdi.dynamicpayroad.domain.DealCommand;
import com.cdi.dynamicpayroad.experiment.DealSource.DealRow;
import com.cdi.dynamicpayroad.redis.MarketOutcome;

import java.time.Instant;
import java.util.SplittableRandom;

/** What an {@link Agent} sees of the running episode. */
public interface EpisodeContext {

    /** The virtual clock's current time. */
    Instant now();

    /** Seconds since the deal was created. */
    double elapsedSec();

    /** Runs {@code action} {@code afterSec} seconds from now (millisecond resolution). Ignored once the deal ended. */
    void schedule(double afterSec, Runnable action);

    /** Sends one command through RedisMarket, logs it, and delivers the resulting events to every agent. */
    MarketOutcome submit(DealCommand command);

    /** The deal as Redis holds it now (get_deal.lua). */
    Deal deal();

    DealRow row();

    /** The episode's only source of randomness. */
    SplittableRandom rng();
}
