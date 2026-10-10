package com.cdi.dynamicpayroad.pricing;

import com.cdi.dynamicpayroad.config.PricingConstants;
import com.cdi.dynamicpayroad.domain.DealRules;
import com.cdi.dynamicpayroad.domain.Geo;
import com.cdi.dynamicpayroad.market.SupplyDemandService;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

/** QuoteClient against a local stand-in for Part B /quote (card A4). */
class QuoteClientTest {

    static final PricingConstants PRICING = new PricingConstants("../config/pricing-constants.json");
    static final String RESPONSE = "{\"basePrice\":184.23,\"baseDry\":160.2,\"distanceKm\":8.42,\"durationMin\":24.3,"
            + "\"avgRainMm\":1.2,\"rainStdMm\":0.4,\"weatherFactor\":1.15,\"surge\":1.0,"
            + "\"routePolyline\":\"_p~iF~ps|U_ulLnnqC\",\"uniqueCells\":4,\"apiCallsUsed\":2,\"method\":\"M2\","
            + "\"fallback\":null}";
    static final double O_LAT = 12.97, O_LNG = 77.59, D_LAT = 12.93, D_LNG = 77.62;
    static final Instant DEPARTURE = Instant.parse("2026-10-08T03:00:00Z");

    private HttpServer server;

    @AfterEach
    void stop() {
        if (server != null) server.stop(0);
    }

    /** Answers every POST /quote with {@code status} and {@code body} after {@code delayMs}; keeps the last request body. */
    private QuoteClient serve(int status, String body, long delayMs, AtomicReference<String> seen) throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.setExecutor(Executors.newCachedThreadPool());
        server.createContext("/quote", ex -> {
            if (seen != null) seen.set(new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            try {
                Thread.sleep(delayMs);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
            byte[] out = body.getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().add("Content-Type", "application/json");
            try {
                ex.sendResponseHeaders(status, out.length);
                try (OutputStream os = ex.getResponseBody()) {
                    os.write(out);
                }
            } catch (IOException ignored) {
                // the client gave up (timeout test)
            }
        });
        server.start();
        return new QuoteClient(PRICING, "http://127.0.0.1:" + server.getAddress().getPort(), 2000);
    }

    @Test
    void answerWithin2sIsUsedAsIs() throws IOException {
        AtomicReference<String> seen = new AtomicReference<>();
        QuoteClient.Quote q = serve(200, RESPONSE, 0, seen).quote(O_LAT, O_LNG, D_LAT, D_LNG, DEPARTURE, 3, 5);

        assertThat(q.basePrice()).isEqualTo(184.23);
        assertThat(q.priceSource()).isEqualTo("QUOTE");
        assertThat(q.distanceKm()).isEqualTo(8.42);
        assertThat(q.durationMin()).isEqualTo(24.3);
        assertThat(q.avgRainMm()).isEqualTo(1.2);
        assertThat(q.weatherFactor()).isEqualTo(1.15);
        assertThat(q.surge()).isEqualTo(1.0);
        assertThat(q.routePolyline()).isEqualTo("_p~iF~ps|U_ulLnnqC");
        assertThat(seen.get()).isEqualTo("{\"origin\":{\"lat\":12.97,\"lng\":77.59},\"dest\":{\"lat\":12.93,\"lng\":77.62},"
                + "\"departureUtc\":\"2026-10-08T03:00:00Z\",\"demand\":3,\"supply\":5}");
    }

    /** uvicorn (Part B) answers an HTTP/2 upgrade request (h2c) with 422, so every live quote fell back. */
    @Test
    void requestIsPlainHttp11WithoutAnUpgradeHeader() throws IOException {
        AtomicReference<String> protocol = new AtomicReference<>();
        AtomicReference<String> upgrade = new AtomicReference<>();
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/quote", ex -> {
            protocol.set(ex.getProtocol());
            upgrade.set(ex.getRequestHeaders().getFirst("Upgrade"));
            ex.getRequestBody().readAllBytes();
            byte[] out = RESPONSE.getBytes(StandardCharsets.UTF_8);
            ex.sendResponseHeaders(200, out.length);
            try (OutputStream os = ex.getResponseBody()) {
                os.write(out);
            }
        });
        server.start();
        QuoteClient client = new QuoteClient(PRICING, "http://127.0.0.1:" + server.getAddress().getPort(), 2000);

        assertThat(client.quote(O_LAT, O_LNG, D_LAT, D_LNG, DEPARTURE, 3, 5).priceSource()).isEqualTo("QUOTE");
        assertThat(protocol.get()).isEqualTo("HTTP/1.1");
        assertThat(upgrade.get()).isNull();
    }

    @Test
    void answerAfter3sFallsBackWithin2_5s() throws IOException {
        QuoteClient client = serve(200, RESPONSE, 3000, null);
        long t0 = System.nanoTime();
        QuoteClient.Quote q = client.quote(O_LAT, O_LNG, D_LAT, D_LNG, DEPARTURE, 3, 5);
        long ms = (System.nanoTime() - t0) / 1_000_000;

        assertThat(q.priceSource()).isEqualTo("FALLBACK");
        assertThat(ms).isLessThan(2500);
    }

    @Test
    void status500FallsBackToStraightLineTimesDetourAndSurge() throws IOException {
        QuoteClient.Quote q = serve(500, "{\"error\":\"boom\"}", 0, null).quote(O_LAT, O_LNG, D_LAT, D_LNG, DEPARTURE, 3, 5);

        double distance = Geo.haversineKm(O_LAT, O_LNG, D_LAT, D_LNG) * DealRules.defaults().detourFactor();
        double surge = SupplyDemandService.surge(3, 5);
        assertThat(surge).isEqualTo(0.7);
        assertThat(q.priceSource()).isEqualTo("FALLBACK");
        assertThat(q.distanceKm()).isEqualTo(distance);
        assertThat(q.durationMin()).isCloseTo(distance / 20.0 * 60, within(1e-9));
        assertThat(q.surge()).isEqualTo(surge);
        // baseFee 0, perKm 18 (config/pricing-constants.json)
        assertThat(q.basePrice()).isEqualTo(Math.round((0 + 18 * distance) * surge * 100.0) / 100.0);
        assertThat(q.avgRainMm()).isEqualTo(0.0);
        assertThat(q.weatherFactor()).isEqualTo(1.0);
        assertThat(q.routePolyline()).isEmpty();
    }

    @Test
    void nobodyListeningFallsBack() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        int port = server.getAddress().getPort();
        server.stop(0);
        server = null;
        QuoteClient.Quote q = new QuoteClient(PRICING, "http://127.0.0.1:" + port, 2000)
                .quote(O_LAT, O_LNG, D_LAT, D_LNG, DEPARTURE, 0, 0);
        assertThat(q.priceSource()).isEqualTo("FALLBACK");
        assertThat(q.surge()).isEqualTo(0.7);
    }
}
