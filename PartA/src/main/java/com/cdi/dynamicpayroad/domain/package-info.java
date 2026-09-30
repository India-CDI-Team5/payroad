/**
 * Bargaining rules (api-spec v1.1, R1-R12) as plain Java: no Spring, no clock, no I/O.
 *
 * <p>{@link com.cdi.dynamicpayroad.domain.DealStateMachine} turns (deal, command, now) into a new
 * deal plus events, or a rejection with an {@link com.cdi.dynamicpayroad.domain.ErrorCode}.
 * {@link com.cdi.dynamicpayroad.domain.MarketStateMachine} adds the rules that span deals (R10, R11).
 * The live service and the virtual-clock experiment runner both call these, so the protocol
 * evaluated in the paper is the one the demo runs.
 */
package com.cdi.dynamicpayroad.domain;
