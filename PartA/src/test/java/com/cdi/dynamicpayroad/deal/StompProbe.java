package com.cdi.dynamicpayroad.deal;

import org.springframework.messaging.converter.MappingJackson2MessageConverter;
import org.springframework.messaging.simp.stomp.StompFrameHandler;
import org.springframework.messaging.simp.stomp.StompHeaders;
import org.springframework.messaging.simp.stomp.StompSession;
import org.springframework.messaging.simp.stomp.StompSessionHandlerAdapter;
import org.springframework.web.socket.client.standard.StandardWebSocketClient;
import org.springframework.web.socket.messaging.WebSocketStompClient;

import java.lang.reflect.Type;
import java.util.Map;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

/** A real STOMP client for tests: one session, a queue per subscription. */
final class StompProbe implements AutoCloseable {

    private final WebSocketStompClient client = new WebSocketStompClient(new StandardWebSocketClient());
    private final StompSession session;

    StompProbe(int port) throws Exception {
        client.setMessageConverter(new MappingJackson2MessageConverter());
        session = client.connectAsync("ws://localhost:" + port + "/ws", new StompSessionHandlerAdapter() {})
                .get(5, TimeUnit.SECONDS);
    }

    @SuppressWarnings("unchecked")
    BlockingQueue<Map<String, Object>> subscribe(String destination) throws InterruptedException {
        BlockingQueue<Map<String, Object>> q = new LinkedBlockingQueue<>();
        session.subscribe(destination, new StompFrameHandler() {
            @Override public Type getPayloadType(StompHeaders headers) { return Map.class; }
            @Override public void handleFrame(StompHeaders headers, Object payload) { q.add((Map<String, Object>) payload); }
        });
        Thread.sleep(200);   // let the broker register the subscription
        return q;
    }

    void send(String destination, Object payload) {
        session.send(destination, payload);
    }

    static Map<String, Object> next(BlockingQueue<Map<String, Object>> q) throws InterruptedException {
        return q.poll(5, TimeUnit.SECONDS);
    }

    static long version(Map<String, Object> event) {
        return ((Number) event.get("version")).longValue();
    }

    @Override
    public void close() {
        session.disconnect();
        client.stop();
    }
}
