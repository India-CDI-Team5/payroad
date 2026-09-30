package com.cdi.dynamicpayroad.deal;

import com.cdi.dynamicpayroad.domain.DealCommand;
import com.cdi.dynamicpayroad.domain.ErrorCode;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.messaging.handler.annotation.DestinationVariable;
import org.springframework.messaging.handler.annotation.MessageMapping;
import org.springframework.messaging.simp.annotation.SendToUser;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * REST (api-spec §4.1-4.3) and STOMP (§5.2) entry points. A rejected STOMP command is answered
 * with an {@code error} event on the sender's own /user/queue/errors; accepted ones produce
 * events on /topic/deal/{dealId} and no reply.
 */
@RestController
public class DealController {

    public record LatLng(double lat, double lng) {}
    public record CreateDealRequest(String riderId, LatLng origin, LatLng dest) {}

    public record BidMessage(String driverId, double price, double driverLat, double driverLng, Long version) {}
    public record WithdrawMessage(String driverId, Long version) {}
    public record OfferMessage(String riderId, double price, Long version) {}
    public record AcceptBidMessage(String riderId, String bidId, Long version) {}
    public record AcceptOfferMessage(String driverId, Long version) {}

    private final DealService deals;

    public DealController(DealService deals) {
        this.deals = deals;
    }

    @PostMapping("/api/deals")
    public ResponseEntity<Map<String, Object>> create(@RequestBody CreateDealRequest req) {
        if (req == null || req.riderId() == null || req.origin() == null || req.dest() == null) {
            return ResponseEntity.badRequest().body(Map.of("message", "riderId, origin and dest are required"));
        }
        return ResponseEntity.status(HttpStatus.CREATED).body(deals.create(req.riderId(),
                req.origin().lat(), req.origin().lng(), req.dest().lat(), req.dest().lng()));
    }

    @GetMapping("/api/deals/{dealId}")
    public ResponseEntity<Map<String, Object>> get(@PathVariable String dealId) {
        return deals.get(dealId).map(ResponseEntity::ok).orElseGet(() -> ResponseEntity.notFound().build());
    }

    /** §4.3. {@code riderId} stands in for authentication, which the system does not have. */
    @DeleteMapping("/api/deals/{dealId}")
    public ResponseEntity<Map<String, Object>> cancel(@PathVariable String dealId, @RequestParam String riderId) {
        DealService.Reply reply = deals.cancel(dealId, riderId);
        if (reply.error() == null && reply.body().get("code") == null) return ResponseEntity.ok(reply.body());
        return ResponseEntity.status(statusOf(reply.error())).body(reply.body());
    }

    @MessageMapping("/deal/{dealId}/bid")
    @SendToUser(destinations = "/queue/errors", broadcast = false)
    public Map<String, Object> bid(@DestinationVariable String dealId, BidMessage m) {
        return deals.handle(dealId, new DealCommand.PlaceBid(m.driverId(), m.price(), m.driverLat(), m.driverLng(), m.version()));
    }

    @MessageMapping("/deal/{dealId}/bid/withdraw")
    @SendToUser(destinations = "/queue/errors", broadcast = false)
    public Map<String, Object> withdraw(@DestinationVariable String dealId, WithdrawMessage m) {
        return deals.handle(dealId, new DealCommand.WithdrawBid(m.driverId(), m.version()));
    }

    @MessageMapping("/deal/{dealId}/offer")
    @SendToUser(destinations = "/queue/errors", broadcast = false)
    public Map<String, Object> offer(@DestinationVariable String dealId, OfferMessage m) {
        return deals.handle(dealId, new DealCommand.PostOffer(m.riderId(), m.price(), m.version()));
    }

    @MessageMapping("/deal/{dealId}/accept-bid")
    @SendToUser(destinations = "/queue/errors", broadcast = false)
    public Map<String, Object> acceptBid(@DestinationVariable String dealId, AcceptBidMessage m) {
        return deals.handle(dealId, new DealCommand.AcceptBid(m.riderId(), m.bidId(), m.version()));
    }

    @MessageMapping("/deal/{dealId}/accept-offer")
    @SendToUser(destinations = "/queue/errors", broadcast = false)
    public Map<String, Object> acceptOffer(@DestinationVariable String dealId, AcceptOfferMessage m) {
        return deals.handle(dealId, new DealCommand.AcceptOffer(m.driverId(), m.version()));
    }

    private static HttpStatus statusOf(ErrorCode code) {
        if (code == null) return HttpStatus.NOT_FOUND;
        return switch (code) {
            case NOT_DEAL_OWNER -> HttpStatus.FORBIDDEN;
            case VERSION_CONFLICT, DEAL_ALREADY_MATCHED, DEAL_NOT_ACTIVE -> HttpStatus.CONFLICT;
            default -> HttpStatus.UNPROCESSABLE_ENTITY;
        };
    }
}
