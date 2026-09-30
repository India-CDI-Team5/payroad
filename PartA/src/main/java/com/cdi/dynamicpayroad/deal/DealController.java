package com.cdi.dynamicpayroad.deal;

import com.cdi.dynamicpayroad.model.Location;
import org.springframework.http.HttpStatus;
import org.springframework.messaging.handler.annotation.DestinationVariable;
import org.springframework.messaging.handler.annotation.MessageMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;

/** REST (§4.1, §4.2) and STOMP (§5.2) entry points for the deal flow. */
@RestController
public class DealController {

    public record LatLng(double lat, double lng) {}
    public record CreateDealRequest(String riderId, LatLng origin, LatLng dest) {}

    private final DealService deals;

    public DealController(DealService deals) {
        this.deals = deals;
    }

    @PostMapping("/api/deals")
    @ResponseStatus(HttpStatus.CREATED)
    public Map<String, Object> create(@RequestBody CreateDealRequest req) {
        return deals.createDeal(req.riderId(),
                new Location(req.origin().lat(), req.origin().lng()),
                new Location(req.dest().lat(), req.dest().lng()));
    }

    @GetMapping("/api/deals/{dealId}")
    public Map<String, Object> get(@PathVariable String dealId) {
        return deals.getDeal(dealId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "deal not found"));
    }

    @MessageMapping("/deal/{dealId}/bid")
    public void bid(@DestinationVariable String dealId, DealService.BidMessage msg) {
        deals.placeBid(dealId, msg);
    }

    @MessageMapping("/deal/{dealId}/accept-bid")
    public void acceptBid(@DestinationVariable String dealId, DealService.AcceptBidMessage msg) {
        deals.acceptBid(dealId, msg);
    }
}
