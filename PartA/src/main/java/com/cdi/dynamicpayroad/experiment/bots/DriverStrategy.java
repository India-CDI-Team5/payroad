package com.cdi.dynamicpayroad.experiment.bots;

/** The four honest driver strategies (ml-design v5 §6.2). The order is the order of bot-params.json "configs". */
public enum DriverStrategy {
    /** Aggressive: high first bid, small steps. */
    AGG,
    /** Conservative: low first bid, large steps. */
    CON,
    /** Distance-sensitive: first bid grows with pickup distance. */
    DIST,
    /** Opportunistic: first bid and step follow how many drivers are bidding. */
    OPP
}
