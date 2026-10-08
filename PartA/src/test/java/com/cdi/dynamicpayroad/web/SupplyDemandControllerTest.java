package com.cdi.dynamicpayroad.web;

import com.cdi.dynamicpayroad.redis.RedisMarket;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpStatus;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * api-spec §4.8 over real HTTP: path, query names and response fields, counted from Redis GEO
 * (SupplyDemandService). Presence endpoints (§4.5-4.7) feed those counts.
 */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "spring.datasource.url=jdbc:h2:mem:supplydemand")
class SupplyDemandControllerTest {

    @Autowired TestRestTemplate rest;
    @Autowired RedisMarket redisMarket;

    @BeforeEach
    void flushRedis() {
        redisMarket.flushDb();
    }

    @Test
    @SuppressWarnings("unchecked")
    void matchesSpec() {
        var r = rest.getForEntity("/api/supply-demand?lat=12.97&lng=77.59", Map.class);
        assertThat(r.getStatusCode()).isEqualTo(HttpStatus.OK);
        Map<String, Object> body = r.getBody();
        assertThat(body).containsOnlyKeys("demand", "supply", "surge", "radiusKm");
        assertThat(body.get("radiusKm")).isEqualTo(5.0);
        assertThat(((Number) body.get("surge")).doubleValue()).isBetween(0.7, 3.0);
    }

    @Test
    @SuppressWarnings("unchecked")
    void registeredDriverAndRiderAreCounted() {
        var driver = rest.postForEntity("/api/presence/driver",
                Map.of("driverId", "DR1", "driverLat", 12.97, "driverLng", 77.59), Map.class);
        assertThat(driver.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(driver.getBody()).containsOnlyKeys("driverId", "status", "expiresAt")
                .containsEntry("driverId", "DR1").containsEntry("status", "ONLINE");

        var rider = rest.postForEntity("/api/presence/rider", Map.of("riderId", "R1"), Map.class);
        assertThat(rider.getBody()).containsOnlyKeys("riderId", "status", "expiresAt").containsEntry("status", "ONLINE");

        // A deal registers its rider at the origin (§4.1), so demand counts them.
        rest.postForEntity("/api/deals", Map.of("riderId", "R2",
                "origin", Map.of("lat", 12.971, "lng", 77.591), "dest", Map.of("lat", 12.93, "lng", 77.62)), Map.class);

        Map<String, Object> sd = rest.getForObject("/api/supply-demand?lat=12.97&lng=77.59", Map.class);
        assertThat(sd).containsEntry("demand", 1).containsEntry("supply", 1).containsEntry("surge", 1.0);
    }

    @Test
    @SuppressWarnings("unchecked")
    void heartbeatShapes() {
        var unknown = rest.postForEntity("/api/presence/heartbeat", Map.of("actorId", "DR9", "actorType", "DRIVER"), Map.class);
        assertThat(unknown.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(unknown.getBody()).isEqualTo(Map.of("ok", false));

        var rider = rest.postForEntity("/api/presence/heartbeat", Map.of("actorId", "R1", "actorType", "RIDER"), Map.class);
        assertThat(rider.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(rider.getBody()).containsOnlyKeys("ok", "expiresAt").containsEntry("ok", true);

        var driver = rest.postForEntity("/api/presence/heartbeat",
                Map.of("actorId", "DR9", "actorType", "DRIVER", "driverLat", 12.97, "driverLng", 77.59), Map.class);
        assertThat(driver.getBody()).containsEntry("ok", true);
    }

    @Test
    void oldPathAndParameterAreGone() {
        assertThat(rest.getForEntity("/supply-demand?lat=12.97&lon=77.59", Map.class).getStatusCode())
                .isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(rest.getForEntity("/api/supply-demand?lat=12.97&lon=77.59", Map.class).getStatusCode())
                .isEqualTo(HttpStatus.BAD_REQUEST);
    }
}
