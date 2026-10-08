package com.cdi.dynamicpayroad.market;

import com.cdi.dynamicpayroad.domain.DealCommand.Cancel;
import com.cdi.dynamicpayroad.domain.DealCommand.PlaceBid;
import com.cdi.dynamicpayroad.domain.DealCommand.PostOffer;
import com.cdi.dynamicpayroad.redis.RedisTestSupport;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/** GET /api/market (api-spec §4.4) on a real Redis (DB 15). */
class MarketControllerTest extends RedisTestSupport {

    static final Instant T0 = Instant.parse("2026-10-01T00:00:00Z");
    static final double LAT = 12.97, LNG = 77.59;
    static final double KM = 1 / 111.0;

    MarketController controller() {
        return new MarketController(market, Clock.fixed(T0.plusSeconds(10), ZoneOffset.UTC));
    }

    void open(String dealId, double lat, double lng) {
        market.createDeal(dealId, "R-" + dealId, lat, lng, 100.0,
                Map.of("destLat", 12.93516, "destLng", 77.62449, "distanceKm", 8.4234), T0);
    }

    @Test
    @SuppressWarnings("unchecked")
    void activeDealsWithinTenKmNearestFirst() {
        open("D-MID", LAT + 6 * KM, LNG);
        open("D-FAR", LAT + 11 * KM, LNG);
        open("D-NEAR", LAT + 1 * KM, LNG);
        open("D-DONE", LAT + 0.5 * KM, LNG);
        market.apply("D-DONE", new Cancel("R-D-DONE"), T0.plusSeconds(1));
        market.upsertPresence("DRIVER", "DR1", LAT, LNG, Duration.ofSeconds(60), T0);
        market.apply("D-NEAR", new PlaceBid("DR1", 150, LAT, LNG, null), T0.plusSeconds(2));
        market.apply("D-NEAR", new PostOffer("R-D-NEAR", 120, null), T0.plusSeconds(3));

        var r = controller().market(LAT, LNG, 30);
        assertThat(r.getStatusCode()).isEqualTo(HttpStatus.OK);
        Map<String, Object> body = r.getBody();
        assertThat(body).containsOnlyKeys("deals", "cells", "generatedAt");
        assertThat(body.get("generatedAt")).isEqualTo(T0.plusSeconds(10).toString());
        assertThat((List<String>) body.get("cells")).hasSize(9);

        List<Map<String, Object>> deals = (List<Map<String, Object>>) body.get("deals");
        assertThat(deals).extracting(d -> d.get("dealId")).containsExactly("D-NEAR", "D-MID");
        Map<String, Object> near = deals.get(0);
        assertThat(near).containsOnlyKeys("dealId", "originApprox", "destApprox", "distanceKm", "basePrice",
                "lowestBidPrice", "riderOfferPrice", "bidderCount", "pendingSide", "expiresAt", "version");
        assertThat(near.get("originApprox")).isEqualTo(Map.of("lat", 12.979, "lng", 77.59));
        assertThat(near.get("destApprox")).isEqualTo(Map.of("lat", 12.935, "lng", 77.624));
        assertThat(near).containsEntry("distanceKm", 8.42).containsEntry("basePrice", 100.0)
                .containsEntry("lowestBidPrice", 150.0).containsEntry("riderOfferPrice", 120.0)
                .containsEntry("bidderCount", 1).containsEntry("pendingSide", "DRIVER")
                .containsEntry("expiresAt", T0.plusSeconds(180).toString()).containsEntry("version", 3L);
        assertThat(deals.get(1)).containsEntry("lowestBidPrice", null).containsEntry("riderOfferPrice", null)
                .containsEntry("bidderCount", 0);
    }

    @Test
    @SuppressWarnings("unchecked")
    void limitCutsTheNearestList() {
        open("D-A", LAT + 1 * KM, LNG);
        open("D-B", LAT + 2 * KM, LNG);
        open("D-C", LAT + 3 * KM, LNG);

        List<Map<String, Object>> deals = (List<Map<String, Object>>) controller().market(LAT, LNG, 2).getBody().get("deals");
        assertThat(deals).extracting(d -> d.get("dealId")).containsExactly("D-A", "D-B");
        assertThat(controller().market(LAT, LNG, 0).getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    }
}
