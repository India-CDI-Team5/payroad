package com.cdi.dynamicpayroad.deal;

import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/** Fires offer TTL (R6) and deal TTL (R7) once a second; deals also refuse actions past their TTL in between. */
@Component
public class ExpirySweeper {

    private final DealService deals;

    public ExpirySweeper(DealService deals) {
        this.deals = deals;
    }

    @Scheduled(fixedRate = 1000)
    public void sweep() {
        deals.tick();
    }
}
