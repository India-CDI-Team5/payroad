package com.cdi.dynamicpayroad.domain;

import java.util.List;

/** Outcome of applying a command: the new state and its events, or a rejection sent only to the requester. */
public sealed interface Result {

    record Accepted(Deal deal, List<DealEvent> events) implements Result {
        public Accepted {
            events = List.copyOf(events);
        }
    }

    /** {@code version} is the deal's current version, echoed in the error event (§5.3, §5.6). */
    record Rejected(ErrorCode code, String message, long version) implements Result {}
}
