package com.cdi.dynamicpayroad.deal;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpStatus;
import org.springframework.messaging.converter.MappingJackson2MessageConverter;
import org.springframework.messaging.simp.stomp.StompFrameHandler;
import org.springframework.messaging.simp.stomp.StompHeaders;
import org.springframework.messaging.simp.stomp.StompSession;
import org.springframework.messaging.simp.stomp.StompSessionHandlerAdapter;
import org.springframework.web.socket.client.standard.StandardWebSocketClient;
import org.springframework.web.socket.messaging.WebSocketStompClient;

import java.lang.reflect.Type;
import java.util.List;
import java.util.Map;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Walking-skeleton check: create deal (REST) -> bid (STOMP) -> accept-bid (STOMP) -> MATCHED,
 * using a real STOMP client against the running app, exactly as the front end would.
 */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "spring.datasource.url=jdbc:h2:mem:dealflow")
class DealFlowTest {

    @LocalServerPort int port;
    @Autowired TestRestTemplate rest;

    @Test
    @SuppressWarnings("unchecked")
    void createDeal_bid_accept_ends_matched() throws Exception {
        // 1) REST: create the deal.
        var created = rest.postForEntity("/api/deals", Map.of(
                "riderId", "R001",
                "origin", Map.of("lat", 12.9716, "lng", 77.5946),
                "dest", Map.of("lat", 12.9352, "lng", 77.6245)), Map.class);
        assertThat(created.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        Map<String, Object> deal = created.getBody();
        String dealId = (String) deal.get("dealId");
        assertThat(deal.get("status")).isEqualTo("OPEN");
        assertThat(deal.get("pendingSide")).isEqualTo("DRIVER");
        assertThat(deal.get("basePrice")).isNotNull();

        // 2) STOMP: connect and subscribe to the deal topic.
        WebSocketStompClient client = new WebSocketStompClient(new StandardWebSocketClient());
        client.setMessageConverter(new MappingJackson2MessageConverter());
        StompSession session = client.connectAsync("ws://localhost:" + port + "/ws",
                new StompSessionHandlerAdapter() {}).get(5, TimeUnit.SECONDS);

        BlockingQueue<Map<String, Object>> events = new LinkedBlockingQueue<>();
        session.subscribe("/topic/deal/" + dealId, new StompFrameHandler() {
            @Override public Type getPayloadType(StompHeaders headers) { return Map.class; }
            @Override public void handleFrame(StompHeaders headers, Object payload) {
                events.add((Map<String, Object>) payload);
            }
        });
        Thread.sleep(300); // let the subscription register before sending

        // 3) Two drivers bid; the rider will later pick the pricier one (rank 2).
        session.send("/app/deal/" + dealId + "/bid", Map.of(
                "driverId", "DR042", "price", 190.0, "driverLat", 12.9401, "driverLng", 77.6102, "version", 1));
        Map<String, Object> first = events.poll(5, TimeUnit.SECONDS);
        assertThat(first).isNotNull();
        assertThat(first.get("event")).isEqualTo("bid.placed");
        assertThat(first.get("bidderCount")).isEqualTo(1);
        assertThat(first.get("pendingSide")).isEqualTo("RIDER");

        session.send("/app/deal/" + dealId + "/bid", Map.of(
                "driverId", "DR017", "price", 215.0, "driverLat", 12.9720, "driverLng", 77.5951, "version", 2));
        Map<String, Object> second = events.poll(5, TimeUnit.SECONDS);
        assertThat(second).isNotNull();
        String pickedBidId = (String) ((Map<String, Object>) second.get("bid")).get("bidId");
        assertThat(second.get("lowestBidPrice")).isEqualTo(190.0);
        assertThat(((Number) second.get("version")).longValue())
                .isGreaterThan(((Number) first.get("version")).longValue());

        // GET reflects NEGOTIATING with bids sorted cheapest first.
        Map<String, Object> mid = rest.getForObject("/api/deals/" + dealId, Map.class);
        assertThat(mid.get("status")).isEqualTo("NEGOTIATING");
        List<Map<String, Object>> bids = (List<Map<String, Object>>) mid.get("bids");
        assertThat(bids).extracting(b -> b.get("price")).containsExactly(190.0, 215.0);

        // 4) Rider accepts the pricier bid -> MATCHED.
        session.send("/app/deal/" + dealId + "/accept-bid", Map.of(
                "riderId", "R001", "bidId", pickedBidId, "version", 3));
        Map<String, Object> matched = events.poll(5, TimeUnit.SECONDS);
        assertThat(matched).isNotNull();
        assertThat(matched.get("event")).isEqualTo("deal.matched");
        assertThat(matched.get("driverId")).isEqualTo("DR017");
        assertThat(matched.get("finalPrice")).isEqualTo(215.0);
        assertThat(matched.get("matchPath")).isEqualTo("RIDER_PICKED_BID");
        assertThat(matched.get("chosenRank")).isEqualTo(2);
        assertThat(matched.get("lowestBidPrice")).isEqualTo(190.0);

        Map<String, Object> end = rest.getForObject("/api/deals/" + dealId, Map.class);
        assertThat(end.get("status")).isEqualTo("MATCHED");

        session.disconnect();
        client.stop();
    }

    @Test
    void unknownDeal_returns404() {
        assertThat(rest.getForEntity("/api/deals/D-nope", Map.class).getStatusCode())
                .isEqualTo(HttpStatus.NOT_FOUND);
    }
}
