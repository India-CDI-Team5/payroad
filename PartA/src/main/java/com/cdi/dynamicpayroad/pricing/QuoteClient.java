package com.cdi.dynamicpayroad.pricing;

import com.cdi.dynamicpayroad.config.PricingConstants;
import com.cdi.dynamicpayroad.domain.DealRules;
import com.cdi.dynamicpayroad.domain.Geo;
import com.cdi.dynamicpayroad.market.SupplyDemandService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.Instant;

/**
 * Part B {@code POST /quote} (plan v6 §3.4, card B8): route, weather and base price for a new deal.
 * When Part B does not answer 200 within the timeout (2 s), the deal opens at the fallback price:
 * straight-line distance × detour, no weather, (baseFee + perKm × distance) × surge.
 */
@Component
public class QuoteClient {

    private static final Logger log = LoggerFactory.getLogger(QuoteClient.class);

    /** What a deal is opened with. {@code priceSource} is QUOTE or FALLBACK (api-spec §4.1). */
    public record Quote(double basePrice, double distanceKm, double durationMin, double avgRainMm,
                        double weatherFactor, double surge, String routePolyline, String priceSource) {}

    private final PricingConstants pricing;
    private final URI endpoint;
    private final Duration timeout;
    private final HttpClient http;
    private final ObjectMapper json = new ObjectMapper();

    public QuoteClient(PricingConstants pricing,
                       @Value("${quote.base-url:http://127.0.0.1:8000}") String baseUrl,
                       @Value("${quote.timeout-ms:2000}") long timeoutMs) {
        this.pricing = pricing;
        this.endpoint = URI.create(baseUrl.replaceAll("/+$", "") + "/quote");
        this.timeout = Duration.ofMillis(timeoutMs);
        // HTTP/1.1: the default HTTP/2 client sends an h2c upgrade request, which uvicorn (Part B) rejects with 422.
        this.http = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).connectTimeout(timeout).build();
    }

    public Quote quote(double oLat, double oLng, double dLat, double dLng, Instant departure, int demand, int supply) {
        try {
            HttpResponse<String> res = http.send(request(oLat, oLng, dLat, dLng, departure, demand, supply),
                    HttpResponse.BodyHandlers.ofString());
            if (res.statusCode() != 200) {
                return fallback(oLat, oLng, dLat, dLng, demand, supply, "HTTP " + res.statusCode());
            }
            JsonNode b = json.readTree(res.body());
            return new Quote(number(b, "basePrice"), number(b, "distanceKm"), number(b, "durationMin"),
                    number(b, "avgRainMm"), number(b, "weatherFactor"), number(b, "surge"),
                    b.path("routePolyline").asText(""), "QUOTE");
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return fallback(oLat, oLng, dLat, dLng, demand, supply, "interrupted");
        } catch (Exception e) {
            return fallback(oLat, oLng, dLat, dLng, demand, supply, e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }

    private HttpRequest request(double oLat, double oLng, double dLat, double dLng, Instant departure,
                                int demand, int supply) throws Exception {
        ObjectNode body = json.createObjectNode();
        body.putObject("origin").put("lat", oLat).put("lng", oLng);
        body.putObject("dest").put("lat", dLat).put("lng", dLng);
        body.put("departureUtc", departure.toString());
        body.put("demand", demand);
        body.put("supply", supply);
        return HttpRequest.newBuilder(endpoint)
                .timeout(timeout)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(json.writeValueAsString(body)))
                .build();
    }

    private Quote fallback(double oLat, double oLng, double dLat, double dLng, int demand, int supply, String reason) {
        DealRules rules = DealRules.defaults();
        double distanceKm = Geo.haversineKm(oLat, oLng, dLat, dLng) * rules.detourFactor();
        double durationMin = distanceKm / rules.avgSpeedKmh() * 60;
        double surge = SupplyDemandService.surge(demand, supply);
        double basePrice = round2((pricing.baseFee() + pricing.perKm() * distanceKm) * surge);
        log.warn("QUOTE FALLBACK {} reason={}", endpoint, reason);
        return new Quote(basePrice, distanceKm, durationMin, 0.0, 1.0, surge, "", "FALLBACK");
    }

    private static double number(JsonNode body, String key) {
        JsonNode v = body.get(key);
        if (v == null || !v.isNumber()) throw new IllegalArgumentException("/quote response has no number " + key);
        return v.doubleValue();
    }

    private static double round2(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
