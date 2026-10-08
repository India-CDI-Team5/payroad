package com.cdi.dynamicpayroad.market;

import com.cdi.dynamicpayroad.domain.DealCommand.AcceptOffer;
import com.cdi.dynamicpayroad.domain.DealCommand.PostOffer;
import com.cdi.dynamicpayroad.redis.RedisTestSupport;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.time.Instant;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class SupplyDemandServiceTest extends RedisTestSupport {

    static final Instant T0 = Instant.parse("2026-10-01T00:00:00Z");
    static final Duration TTL = Duration.ofSeconds(60);
    static final double LAT = 12.97, LNG = 77.59;
    /** About 1.1 km per 0.01° of latitude. */
    static final double KM = 1 / 111.0;

    @Test
    void surgeFormulaIsTheSameAsMatchingEngine() {
        assertThat(SupplyDemandService.surge(0, 0)).isEqualTo(0.7);
        assertThat(SupplyDemandService.surge(2, 0)).isEqualTo(2.0);
        assertThat(SupplyDemandService.surge(9, 0)).isEqualTo(3.0);
        assertThat(SupplyDemandService.surge(3, 3)).isEqualTo(1.0);
        assertThat(SupplyDemandService.surge(1, 10)).isEqualTo(0.7);
        assertThat(SupplyDemandService.surge(40, 10)).isEqualTo(3.0);
        assertThat(SupplyDemandService.surge(7, 3)).isEqualTo(2.3);
    }

    @Test
    void countsOnlyPeopleWithinFiveKmAndNotMatchedDrivers() {
        market.upsertPresence("DRIVER", "IN1", LAT + 1 * KM, LNG, TTL, T0);
        market.upsertPresence("DRIVER", "IN2", LAT - 4.8 * KM, LNG, TTL, T0);
        market.upsertPresence("DRIVER", "OUT", LAT + 5.2 * KM, LNG, TTL, T0);
        market.upsertPresence("RIDER", "R-IN", LAT, LNG + 2 * KM, TTL, T0);
        market.upsertPresence("RIDER", "R-OUT", LAT + 8 * KM, LNG, TTL, T0);
        // A rider who opens a deal is counted at its origin.
        market.createDeal("D-1", "R-DEAL", LAT, LNG, 100.0, Map.of(), T0);

        SupplyDemandService service = new SupplyDemandService(market);
        assertThat(service.at(LAT, LNG)).isEqualTo(new SupplyDemandService.Snapshot(2, 2, 1.0));

        // A MATCHED driver leaves geo:drivers (R10), so supply drops.
        market.apply("D-1", new PostOffer("R-DEAL", 120, null), T0.plusSeconds(1));
        market.apply("D-1", new AcceptOffer("IN1", null), T0.plusSeconds(2));
        assertThat(service.at(LAT, LNG)).isEqualTo(new SupplyDemandService.Snapshot(2, 1, 2.0));
    }
}
