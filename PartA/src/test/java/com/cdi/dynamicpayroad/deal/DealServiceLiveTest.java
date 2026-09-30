package com.cdi.dynamicpayroad.deal;

import com.cdi.dynamicpayroad.model.DealHistory;
import com.cdi.dynamicpayroad.repository.DealHistoryRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.Map;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.TimeUnit;

import static com.cdi.dynamicpayroad.deal.StompProbe.next;
import static org.assertj.core.api.Assertions.assertThat;

/** Error routing, cancel, expiry and retention of the live service, with time moved by a test clock. */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "spring.datasource.url=jdbc:h2:mem:deallive")
class DealServiceLiveTest {

    /** A clock the test can move; the expiry sweeper reads it every second. */
    static final class MovableClock extends Clock {
        private volatile Instant now = Instant.parse("2026-10-01T00:00:00Z");
        void advance(Duration d) { now = now.plus(d); }
        @Override public Instant instant() { return now; }
        @Override public ZoneId getZone() { return ZoneOffset.UTC; }
        @Override public Clock withZone(ZoneId zone) { return this; }
    }

    @TestConfiguration
    static class Config {
        @Bean @Primary MovableClock movableClock() { return new MovableClock(); }
    }

    @LocalServerPort int port;
    @Autowired TestRestTemplate rest;
    @Autowired DealHistoryRepository history;
    @Autowired MovableClock clock;

    @SuppressWarnings("unchecked")
    String createDeal(String riderId) {
        Map<String, Object> body = rest.postForEntity("/api/deals", Map.of(
                "riderId", riderId,
                "origin", Map.of("lat", 12.9716, "lng", 77.5946),
                "dest", Map.of("lat", 12.9352, "lng", 77.6245)), Map.class).getBody();
        return (String) body.get("dealId");
    }

    DealHistory row(String dealId) {
        return history.findAll().stream().filter(h -> dealId.equals(h.getDealId())).findFirst().orElse(null);
    }

    @Test
    void rejectionGoesOnlyToTheSender() throws Exception {
        String dealId = createDeal("R100");
        try (StompProbe driver = new StompProbe(port); StompProbe watcher = new StompProbe(port)) {
            BlockingQueue<Map<String, Object>> driverErrors = driver.subscribe("/user/queue/errors");
            BlockingQueue<Map<String, Object>> watcherErrors = watcher.subscribe("/user/queue/errors");
            BlockingQueue<Map<String, Object>> topic = watcher.subscribe("/topic/deal/" + dealId);

            driver.send("/app/deal/" + dealId + "/bid", Map.of(
                    "driverId", "DR1", "price", 5.0, "driverLat", 12.98, "driverLng", 77.60, "version", 1));
            Map<String, Object> error = next(driverErrors);
            assertThat(error).containsEntry("event", "error").containsEntry("code", "OUT_OF_BAND")
                    .containsEntry("dealId", dealId).containsEntry("version", 1);

            assertThat(watcherErrors.poll(500, TimeUnit.MILLISECONDS)).isNull();
            assertThat(topic.poll(100, TimeUnit.MILLISECONDS)).isNull();

            // A message missing its actor id is refused, not waved through.
            driver.send("/app/deal/" + dealId + "/offer", Map.of("price", 150.0, "version", 1));
            assertThat(next(driverErrors)).containsEntry("code", "NOT_DEAL_OWNER");
        }
    }

    @Test
    @SuppressWarnings("unchecked")
    void cancelIsOwnerOnlyAndIsRecorded() throws Exception {
        String dealId = createDeal("R200");
        try (StompProbe probe = new StompProbe(port)) {
            BlockingQueue<Map<String, Object>> topic = probe.subscribe("/topic/deal/" + dealId);

            var stranger = rest.exchange("/api/deals/" + dealId + "?riderId=R999", HttpMethod.DELETE, null, Map.class);
            assertThat(stranger.getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN);
            assertThat(stranger.getBody()).containsEntry("code", "NOT_DEAL_OWNER");

            var owner = rest.exchange("/api/deals/" + dealId + "?riderId=R200", HttpMethod.DELETE, null, Map.class);
            assertThat(owner.getStatusCode()).isEqualTo(HttpStatus.OK);
            assertThat(owner.getBody()).containsEntry("status", "CANCELLED");
            assertThat(next(topic)).containsEntry("event", "deal.expired").containsEntry("reason", "CANCELLED_BY_RIDER");
        }
        assertThat(row(dealId).getEndStatus()).isEqualTo("CANCELLED");
        assertThat(rest.exchange("/api/deals/D-nope?riderId=R200", HttpMethod.DELETE, null, Map.class).getStatusCode())
                .isEqualTo(HttpStatus.NOT_FOUND);
    }

    @Test
    @SuppressWarnings("unchecked")
    void sweeperExpiresAtTtlAndDropsAfterRetention() throws Exception {
        String dealId = createDeal("R300");
        try (StompProbe probe = new StompProbe(port)) {
            BlockingQueue<Map<String, Object>> topic = probe.subscribe("/topic/deal/" + dealId);
            clock.advance(Duration.ofSeconds(181));
            Map<String, Object> expired = topic.poll(4, TimeUnit.SECONDS);
            assertThat(expired).containsEntry("event", "deal.expired").containsEntry("reason", "TTL");
        }
        assertThat(rest.getForObject("/api/deals/" + dealId, Map.class).get("status")).isEqualTo("EXPIRED");
        DealHistory r = row(dealId);
        assertThat(r.getEndStatus()).isEqualTo("EXPIRED");
        assertThat(r.getEndReason()).isEqualTo("TTL");
        assertThat(r.getNegotiationDurationMs()).isGreaterThanOrEqualTo(180_000);

        clock.advance(Duration.ofSeconds(120));   // 301 s after creation: past the 300 s retention
        long deadline = System.currentTimeMillis() + 4000;
        HttpStatus status = HttpStatus.OK;
        while (System.currentTimeMillis() < deadline && status == HttpStatus.OK) {
            status = (HttpStatus) rest.getForEntity("/api/deals/" + dealId, Map.class).getStatusCode();
            Thread.sleep(200);
        }
        assertThat(status).isEqualTo(HttpStatus.NOT_FOUND);
    }
}
