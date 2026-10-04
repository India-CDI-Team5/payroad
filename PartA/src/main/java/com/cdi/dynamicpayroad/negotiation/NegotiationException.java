package com.cdi.dynamicpayroad.negotiation;

/** Wraps a Redis Lua error_reply code (e.g. PRICE_NOT_CONCEDED, DEAL_ALREADY_MATCHED). */
public class NegotiationException extends RuntimeException {
    public NegotiationException(String code) {
        super(code);
    }
}
