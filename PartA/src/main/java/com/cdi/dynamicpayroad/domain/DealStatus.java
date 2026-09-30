package com.cdi.dynamicpayroad.domain;

/** Deal lifecycle (api-spec §3). OPEN and NEGOTIATING accept actions; the rest are terminal. */
public enum DealStatus {
    OPEN, NEGOTIATING, MATCHED, EXPIRED, CANCELLED;

    public boolean isActive() {
        return this == OPEN || this == NEGOTIATING;
    }
}
