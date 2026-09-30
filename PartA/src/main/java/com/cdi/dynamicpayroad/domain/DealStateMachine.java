package com.cdi.dynamicpayroad.domain;

import java.time.Instant;

/**
 * Rules that concern a single deal: R1-R9 and R12 (api-spec §2).
 * Pure: the same (deal, command, drivers, now) always gives the same result.
 *
 * <p>Check order for every command: deal active (DEAL_NOT_ACTIVE / DEAL_ALREADY_MATCHED),
 * then ownership and availability (NOT_DEAL_OWNER, DRIVER_NOT_AVAILABLE), then version
 * (VERSION_CONFLICT), then the command's own rules.
 */
public final class DealStateMachine {

    /** Whether a driver may act right now (R11). Supplied by the market. */
    @FunctionalInterface
    public interface DriverAvailability {
        boolean isAvailable(String driverId);

        DriverAvailability ALL = driverId -> true;
    }

    private final DealRules rules;

    public DealStateMachine(DealRules rules) {
        this.rules = rules;
    }

    public DealRules rules() {
        return rules;
    }

    public Result apply(Deal deal, DealCommand command, DriverAvailability drivers, Instant now) {
        throw new UnsupportedOperationException("DealStateMachine is not implemented yet (milestone 10/2-10/3)");
    }
}
