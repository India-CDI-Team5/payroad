package com.cdi.dynamicpayroad.experiment.bots;

/** The planted collusion strategies (ml-design v5 §7.2). S5 is the blind one (card D5). */
public enum CollusionStrategy {
    /** Price floor: never below 1.25 × base_price, never under a fellow member's live bid. */
    S1,
    /** Cover bids: one designated winner; the others bid just above it and withdraw. */
    S2,
    /** Rotation: one member competes per deal, the others abstain or bid high once. */
    S3,
    /** Synchronised matching: enter late, together, at the lowest honest bid (pre-registered holdout). */
    S4,
    /**
     * Offer refusal (blind, card D5, docs/collusion-s5.md): when members meet, the rider's offers
     * are left to the member with the closest pickup, who takes them only from a reserve up; the
     * others never accept an offer and stop conceding once the rider has offered.
     */
    S5
}
