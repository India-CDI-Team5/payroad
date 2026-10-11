package com.cdi.dynamicpayroad.experiment.bots;

/** The planted collusion strategies (ml-design v5 §7.2). S5 is added in card D5. */
public enum CollusionStrategy {
    /** Price floor: never below 1.25 × base_price, never under a fellow member's live bid. */
    S1,
    /** Cover bids: one designated winner; the others bid just above it and withdraw. */
    S2,
    /** Rotation: one member competes per deal, the others abstain or bid high once. */
    S3,
    /** Synchronised matching: enter late, together, at the lowest honest bid (pre-registered holdout). */
    S4
}
