package com.cdi.dynamicpayroad.redis;

import com.cdi.dynamicpayroad.domain.DealEvent;
import com.cdi.dynamicpayroad.domain.ErrorCode;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;

/**
 * One Lua script reply (api-spec §6.6).
 *
 * <p>{@code ok = false}: rejected, nothing changed; {@code code}/{@code message}/{@code version}
 * go to the requester ({@code version} is 0 when the deal does not exist).
 *
 * <p>{@code ok = true}: {@code events} per deal id in the order the script produced them,
 * {@code closed} lists deals that ended in this call (at {@code closedAt}), and
 * {@code requesterError*} is set when the action hit the round limit (R8): the deal closed and
 * the requester still gets ROUND_LIMIT_EXCEEDED.
 */
public record MarketOutcome(
        boolean ok,
        ErrorCode code,
        String message,
        long version,
        LinkedHashMap<String, List<DealEvent>> events,
        List<String> closed,
        Instant closedAt,
        ErrorCode requesterErrorCode,
        String requesterErrorMessage,
        long requesterErrorVersion) {
}
