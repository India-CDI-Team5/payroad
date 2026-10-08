package com.cdi.dynamicpayroad.deal;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Runs sweep.lua once a second (api-spec §6.5): deal TTL (R7), offer TTL (R6), physical deletion.
 * Deals also refuse actions past their TTL in between. Off in JUnit unless a test turns it on.
 */
@Component
@ConditionalOnProperty(name = "deal.sweeper.enabled", havingValue = "true", matchIfMissing = true)
public class ExpirySweeper {

    private final DealService deals;

    public ExpirySweeper(DealService deals) {
        this.deals = deals;
    }

    @Scheduled(fixedRate = 1000)
    public void sweep() {
        deals.sweep();
    }
}
