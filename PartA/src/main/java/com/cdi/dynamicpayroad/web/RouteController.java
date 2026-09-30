package com.cdi.dynamicpayroad.web;

import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.server.ResponseStatusException;

import java.time.Duration;
import java.util.List;
import java.util.Map;

/**
 * Road-route lookup for the dashboard. The browser asks us, we call OpenRouteService
 * with the API key, so the key never leaves the server.
 */
@RestController
public class RouteController {

    private static final String ORS_URL =
            "https://api.openrouteservice.org/v2/directions/driving-car/geojson";

    public record Point(double lat, double lon) {}
    public record RouteRequest(Point start, Point end) {}

    private final RestClient ors;
    private final String apiKey;

    public RouteController(@Value("${ors.api-key:}") String apiKey) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofSeconds(5));
        factory.setReadTimeout(Duration.ofSeconds(10));
        this.ors = RestClient.builder().requestFactory(factory).build();
        this.apiKey = unquote(apiKey);
    }

    /**
     * The .env file is written for python-dotenv, which strips surrounding quotes, but Spring's
     * [.properties] import keeps them, so ORS would receive `"key"` and answer 403.
     */
    static String unquote(String value) {
        String v = value.strip();
        if (v.length() >= 2 && (v.startsWith("\"") && v.endsWith("\"") || v.startsWith("'") && v.endsWith("'"))) {
            return v.substring(1, v.length() - 1);
        }
        return v;
    }

    @PostMapping("/api/route")
    public JsonNode route(@RequestBody RouteRequest req) {
        if (apiKey.isBlank()) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "ORS_API_KEY is not configured");
        }
        if (req == null || req.start() == null || req.end() == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "start and end are required");
        }
        try {
            return ors.post()
                    .uri(ORS_URL)
                    .header("Authorization", apiKey)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of(
                            "coordinates", List.of(
                                    List.of(req.start().lon(), req.start().lat()),
                                    List.of(req.end().lon(), req.end().lat())),
                            "instructions", false))
                    .retrieve()
                    .body(JsonNode.class);
        } catch (RestClientException e) {
            // Deliberately generic: the upstream message/headers must not leak the key.
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "route lookup failed");
        }
    }
}
