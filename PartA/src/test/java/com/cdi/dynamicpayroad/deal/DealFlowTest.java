package com.cdi.dynamicpayroad.deal;

import com.cdi.dynamicpayroad.model.DealHistory;
import com.cdi.dynamicpayroad.repository.DealHistoryRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpStatus;

import java.util.List;
import java.util.Map;
import java.util.concurrent.BlockingQueue;

import static com.cdi.dynamicpayroad.deal.StompProbe.next;
import static com.cdi.dynamicpayroad.deal.StompProbe.version;
import static org.assertj.core.api.Assertions.assertThat;

/**
 * The full path the front end takes: create deal (REST) -> two bids (STOMP) -> rider picks the
 * pricier one (STOMP) -> MATCHED, with the rules of domain/ applied and a DealHistory row written.
 */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "spring.datasource.url=jdbc:h2:mem:dealflow")
class DealFlowTest {

    @LocalServerPort int port;
    @Autowired TestRestTemplate rest;
    @Autowired DealHistoryRepository history;

    @Test
    @SuppressWarnings("unchecked")
    void createDeal_bid_accept_ends_matched() throws Exception {
        var created = rest.postForEntity("/api/deals", Map.of(
                "riderId", "R001",
                "origin", Map.of("lat", 12.9716, "lng", 77.5946),
                "dest", Map.of("lat", 12.9352, "lng", 77.6245)), Map.class);
        assertThat(created.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        Map<String, Object> deal = created.getBody();
        String dealId = (String) deal.get("dealId");
        assertThat(deal).containsEntry("status", "OPEN").containsEntry("pendingSide", "DRIVER");
        assertThat(version(deal)).isEqualTo(1);
        assertThat((Map<String, Object>) deal.get("priceBand")).containsKeys("min", "max");

        try (StompProbe probe = new StompProbe(port)) {
            BlockingQueue<Map<String, Object>> events = probe.subscribe("/topic/deal/" + dealId);
            BlockingQueue<Map<String, Object>> errors = probe.subscribe("/user/queue/errors");

            probe.send("/app/deal/" + dealId + "/bid", Map.of(
                    "driverId", "DR042", "price", 190.0, "driverLat", 12.9401, "driverLng", 77.6102, "version", 1));
            Map<String, Object> first = next(events);
            assertThat(first).containsEntry("event", "bid.placed").containsEntry("pendingSide", "RIDER");
            assertThat(version(first)).isEqualTo(2);

            probe.send("/app/deal/" + dealId + "/bid", Map.of(
                    "driverId", "DR017", "price", 215.0, "driverLat", 12.9720, "driverLng", 77.5951, "version", version(first)));
            Map<String, Object> second = next(events);
            assertThat(second).containsEntry("lowestBidPrice", 190.0).containsEntry("bidderCount", 2);
            String pricier = (String) ((Map<String, Object>) second.get("bid")).get("bidId");

            Map<String, Object> mid = rest.getForObject("/api/deals/" + dealId, Map.class);
            assertThat(mid.get("status")).isEqualTo("NEGOTIATING");
            assertThat((List<Map<String, Object>>) mid.get("bids")).extracting(b -> b.get("price")).containsExactly(190.0, 215.0);

            probe.send("/app/deal/" + dealId + "/accept-bid", Map.of(
                    "riderId", "R001", "bidId", pricier, "version", version(second)));
            Map<String, Object> matched = next(events);
            assertThat(matched).containsEntry("event", "deal.matched").containsEntry("driverId", "DR017")
                    .containsEntry("finalPrice", 215.0).containsEntry("matchPath", "RIDER_PICKED_BID")
                    .containsEntry("chosenRank", 2).containsEntry("lowestBidPrice", 190.0);
            assertThat(errors).isEmpty();
        }

        assertThat(rest.getForObject("/api/deals/" + dealId, Map.class).get("status")).isEqualTo("MATCHED");
        DealHistory row = history.findAll().stream().filter(h -> dealId.equals(h.getDealId())).findFirst().orElseThrow();
        assertThat(row.getEndStatus()).isEqualTo("MATCHED");
        assertThat(row.getChosenRank()).isEqualTo(2);
        assertThat(row.getMatchPath()).isEqualTo("RIDER_PICKED_BID");
        assertThat(row.getFinalPrice()).isEqualTo(215.0);
        assertThat(row.getBidderCount()).isEqualTo(2);
        assertThat(row.getRoundCount()).isEqualTo(2);
        assertThat(row.getMarkupRatio()).isEqualTo(215.0 / row.getBasePrice());
    }

    @Test
    void unknownDeal_returns404() {
        assertThat(rest.getForEntity("/api/deals/D-nope", Map.class).getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
    }
}
