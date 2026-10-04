package com.cdi.dynamicpayroad.negotiation;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/negotiation")
public class NegotiationController {

    private final NegotiationService negotiationService;

    public NegotiationController(NegotiationService negotiationService) {
        this.negotiationService = negotiationService;
    }

    public record CreateDealRequest(String riderId, double basePrice) {}
    public record BidRequest(String driverId, double price) {}
    public record AcceptBidRequest(String driverId) {}

    @PostMapping("/deals")
    public Map<String, String> createDeal(@RequestBody CreateDealRequest req) {
        String dealId = negotiationService.createDeal(req.riderId(), req.basePrice());
        return Map.of("dealId", dealId, "status", "OPEN");
    }

    @GetMapping("/deals/{dealId}")
    public Map<Object, Object> getDeal(@PathVariable String dealId) {
        return negotiationService.getDeal(dealId);
    }

    @PostMapping("/deals/{dealId}/bids")
    public ResponseEntity<?> placeBid(@PathVariable String dealId, @RequestBody BidRequest req) {
        try {
            long version = negotiationService.placeBid(dealId, req.driverId(), req.price());
            return ResponseEntity.ok(Map.of("dealId", dealId, "driverId", req.driverId(), "version", version));
        } catch (NegotiationException e) {
            return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/deals/{dealId}/accept-bid")
    public ResponseEntity<?> acceptBid(@PathVariable String dealId, @RequestBody AcceptBidRequest req) {
        try {
            long version = negotiationService.acceptBid(dealId, req.driverId());
            return ResponseEntity.ok(Map.of("dealId", dealId, "matchedDriver", req.driverId(), "version", version));
        } catch (NegotiationException e) {
            return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of("error", e.getMessage()));
        }
    }
}
