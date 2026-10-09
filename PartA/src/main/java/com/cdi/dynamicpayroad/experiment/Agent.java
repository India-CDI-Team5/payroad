package com.cdi.dynamicpayroad.experiment;

import com.cdi.dynamicpayroad.domain.DealEvent;

import java.util.Optional;

/**
 * A bot taking part in one episode: the rider or one driver. It acts only through
 * {@link EpisodeContext#submit} and {@link EpisodeContext#schedule}, so the episode stays on one
 * thread and one clock.
 */
public interface Agent {

    enum ActorType { DRIVER, RIDER }

    /** Driver id, or {@link EpisodeEngine#RIDER_ID} for the rider. */
    String id();

    ActorType actorType();

    /** Strategy name for labels.csv and deals_out.csv (winner_strategy). */
    default String strategy() {
        return "";
    }

    /** Hidden collusion role, written only to labels.csv and deals_out.csv. */
    default boolean colluder() {
        return false;
    }

    /**
     * A driver's {lat, lng} for this episode: presence is registered there and its bids carry it.
     * Empty means the deal's origin.
     */
    default Optional<double[]> position() {
        return Optional.empty();
    }

    /** Called once after the deal is created and drivers are present, at t = 0. */
    void onStart(EpisodeContext ctx);

    /** Every event of this deal, in the order the Lua scripts produced them. */
    void onEvent(EpisodeContext ctx, DealEvent e);
}
