package com.cdi.dynamicpayroad.presence;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

/** Presence endpoints, request and response shapes of api-spec §4.5-4.7. */
@RestController
public class PresenceController {

    public record DriverRequest(String driverId, Double driverLat, Double driverLng) {}
    public record RiderRequest(String riderId) {}
    public record HeartbeatRequest(String actorId, String actorType, Double driverLat, Double driverLng) {}

    private final PresenceService presence;

    public PresenceController(PresenceService presence) {
        this.presence = presence;
    }

    /** §4.5: {driverId, status (ONLINE | MATCHED), expiresAt}. */
    @PostMapping("/api/presence/driver")
    public ResponseEntity<Map<String, Object>> driver(@RequestBody DriverRequest req) {
        if (req == null || blank(req.driverId()) || req.driverLat() == null || req.driverLng() == null) {
            return ResponseEntity.badRequest().body(Map.of("message", "driverId, driverLat and driverLng are required"));
        }
        Instant expiresAt = presence.registerDriver(req.driverId(), req.driverLat(), req.driverLng());
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("driverId", req.driverId());
        body.put("status", presence.driverStatus(req.driverId()));
        body.put("expiresAt", expiresAt.toString());
        return ResponseEntity.ok(body);
    }

    /** §4.6: {riderId, status: "ONLINE", expiresAt}. */
    @PostMapping("/api/presence/rider")
    public ResponseEntity<Map<String, Object>> rider(@RequestBody RiderRequest req) {
        if (req == null || blank(req.riderId())) {
            return ResponseEntity.badRequest().body(Map.of("message", "riderId is required"));
        }
        Instant expiresAt = presence.registerRider(req.riderId(), null, null);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("riderId", req.riderId());
        body.put("status", "ONLINE");
        body.put("expiresAt", expiresAt.toString());
        return ResponseEntity.ok(body);
    }

    /** §4.7: {ok: true, expiresAt}, or 400 {ok: false} (unregistered driver without a position, bad request). */
    @PostMapping("/api/presence/heartbeat")
    public ResponseEntity<Map<String, Object>> heartbeat(@RequestBody HeartbeatRequest req) {
        if (req == null || blank(req.actorId())
                || !("DRIVER".equals(req.actorType()) || "RIDER".equals(req.actorType()))) {
            return ResponseEntity.badRequest().body(Map.of("ok", false));
        }
        Optional<Instant> expiresAt = presence.heartbeat(req.actorId(), req.actorType(), req.driverLat(), req.driverLng());
        return expiresAt
                .<ResponseEntity<Map<String, Object>>>map(t -> ResponseEntity.ok(Map.of("ok", true, "expiresAt", t.toString())))
                .orElseGet(() -> ResponseEntity.badRequest().body(Map.of("ok", false)));
    }

    private static boolean blank(String s) {
        return s == null || s.isBlank();
    }
}
