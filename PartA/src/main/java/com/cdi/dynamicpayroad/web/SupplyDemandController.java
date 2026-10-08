package com.cdi.dynamicpayroad.web;

import com.cdi.dynamicpayroad.market.SupplyDemandService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/** Liveness check and local demand/supply/surge lookup (api-spec §4.8). */
@RestController
public class SupplyDemandController {

    private final SupplyDemandService supplyDemand;

    public SupplyDemandController(SupplyDemandService supplyDemand) {
        this.supplyDemand = supplyDemand;
    }

    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of("status", "ok");
    }

    @GetMapping("/api/supply-demand")
    public Map<String, Object> supplyDemand(@RequestParam double lat, @RequestParam double lng) {
        SupplyDemandService.Snapshot s = supplyDemand.at(lat, lng);
        return Map.of(
                "demand", s.demand(),
                "supply", s.supply(),
                "surge", s.surge(),
                "radiusKm", SupplyDemandService.RADIUS_KM
        );
    }
}
