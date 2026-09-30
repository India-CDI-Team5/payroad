package com.cdi.dynamicpayroad.web;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpStatus;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/** api-spec §4.8 over real HTTP: path, query names and response fields. */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "spring.datasource.url=jdbc:h2:mem:supplydemand")
class SupplyDemandControllerTest {

    @Autowired TestRestTemplate rest;

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
    void oldPathAndParameterAreGone() {
        assertThat(rest.getForEntity("/supply-demand?lat=12.97&lon=77.59", Map.class).getStatusCode())
                .isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(rest.getForEntity("/api/supply-demand?lat=12.97&lon=77.59", Map.class).getStatusCode())
                .isEqualTo(HttpStatus.BAD_REQUEST);
    }
}
