package com.cdi.dynamicpayroad.web;

import com.cdi.dynamicpayroad.engine.MatchingEngine;
import com.cdi.dynamicpayroad.model.Location;
import com.cdi.dynamicpayroad.pool.OnlinePool;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/** Liveness check and local demand/supply/surge lookup (api-spec §4.8). */
@RestController
public class SupplyDemandController {

    private final OnlinePool pool;
    private final MatchingEngine matching;

    public SupplyDemandController(OnlinePool pool, MatchingEngine matching) {
        this.pool = pool;
        this.matching = matching;
    }

    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of("status", "ok");
    }

    @GetMapping("/api/supply-demand")
    public Map<String, Object> supplyDemand(@RequestParam double lat, @RequestParam double lng) {
        MatchingEngine.Outcome outcome = matching.evaluateAt(
                new Location(lat, lng), pool.users(), pool.waitingDrivers());
        return Map.of(
                "demand", outcome.demandInRadius(),
                "supply", outcome.supplyInRadius(),
                "surge", outcome.surge(),
                "radiusKm", MatchingEngine.RADIUS_KM
        );
    }
}
