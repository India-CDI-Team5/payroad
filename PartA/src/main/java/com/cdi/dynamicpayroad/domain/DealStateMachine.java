package com.cdi.dynamicpayroad.domain;

import com.cdi.dynamicpayroad.domain.DealCommand.AcceptBid;
import com.cdi.dynamicpayroad.domain.DealCommand.AcceptOffer;
import com.cdi.dynamicpayroad.domain.DealCommand.Cancel;
import com.cdi.dynamicpayroad.domain.DealCommand.PlaceBid;
import com.cdi.dynamicpayroad.domain.DealCommand.PostOffer;
import com.cdi.dynamicpayroad.domain.DealCommand.Tick;
import com.cdi.dynamicpayroad.domain.DealCommand.WithdrawBid;
import com.cdi.dynamicpayroad.domain.DealEvent.BidPlaced;
import com.cdi.dynamicpayroad.domain.DealEvent.BidUpdated;
import com.cdi.dynamicpayroad.domain.DealEvent.BidWithdrawn;
import com.cdi.dynamicpayroad.domain.DealEvent.DealExpired;
import com.cdi.dynamicpayroad.domain.DealEvent.OfferPosted;
import com.cdi.dynamicpayroad.domain.Enums.EndReason;
import com.cdi.dynamicpayroad.domain.Enums.PendingSide;
import com.cdi.dynamicpayroad.domain.Enums.WithdrawReason;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Rules that concern a single deal: R1-R9 and R12 (api-spec §2).
 * Pure: the same (deal, command, drivers, now) always gives the same result.
 *
 * <p>Check order for every command: deal active (DEAL_NOT_ACTIVE / DEAL_ALREADY_MATCHED),
 * then ownership and availability (NOT_DEAL_OWNER, DRIVER_NOT_AVAILABLE), then version
 * (VERSION_CONFLICT), then the command's own rules.
 *
 * <p>Implemented: R1, R2, R5, R11 (driver availability, rider ownership), R12.
 * Accepting (R3, R9) and timeouts (R6, R7) come next (milestone 10/3); R8 rounds are counted
 * but not yet capped.
 */
public final class DealStateMachine {

    /** Whether a driver may act right now (R11). Supplied by the market. */
    @FunctionalInterface
    public interface DriverAvailability {
        boolean isAvailable(String driverId);

        DriverAvailability ALL = driverId -> true;
    }

    private final DealRules rules;

    public DealStateMachine(DealRules rules) {
        this.rules = rules;
    }

    public DealRules rules() {
        return rules;
    }

    public Result apply(Deal deal, DealCommand command, DriverAvailability drivers, Instant now) {
        if (!deal.status().isActive()) {
            if (command instanceof Tick) return new Result.Accepted(deal, List.of());
            return deal.status() == DealStatus.MATCHED
                    ? reject(deal, ErrorCode.DEAL_ALREADY_MATCHED, "이미 체결된 거래입니다")
                    : reject(deal, ErrorCode.DEAL_NOT_ACTIVE, "종료된 거래입니다");
        }

        Result refused = checkActor(deal, command, drivers);
        if (refused != null) return refused;
        refused = checkVersion(deal, command);
        if (refused != null) return refused;

        return switch (command) {
            case PlaceBid c -> placeBid(deal, c, now);
            case WithdrawBid c -> withdrawBid(deal, c);
            case PostOffer c -> postOffer(deal, c, now);
            case Cancel c -> cancel(deal);
            case AcceptBid c -> throw new UnsupportedOperationException("R3/R9 accept-bid: milestone 10/3");
            case AcceptOffer c -> throw new UnsupportedOperationException("R3/R6/R9 accept-offer: milestone 10/3");
            case Tick c -> throw new UnsupportedOperationException("R6/R7 timeouts: milestone 10/3");
        };
    }

    // --- common checks ---------------------------------------------------------------------

    /** R11: riders act only on their own deal; drivers only while available. */
    private Result checkActor(Deal deal, DealCommand command, DriverAvailability drivers) {
        String rider = switch (command) {
            case PostOffer c -> c.riderId();
            case AcceptBid c -> c.riderId();
            case Cancel c -> c.riderId();
            default -> null;
        };
        if (rider != null && !rider.equals(deal.riderId())) {
            return reject(deal, ErrorCode.NOT_DEAL_OWNER, "본인의 거래가 아닙니다");
        }
        String driver = switch (command) {
            case PlaceBid c -> c.driverId();
            case WithdrawBid c -> c.driverId();
            case AcceptOffer c -> c.driverId();
            default -> null;
        };
        if (driver != null && !drivers.isAvailable(driver)) {
            return reject(deal, ErrorCode.DRIVER_NOT_AVAILABLE, "지금은 호가·수락을 할 수 없는 기사입니다");
        }
        return null;
    }

    /** §5.6: a command carrying a version must match the deal's current one. */
    private Result checkVersion(Deal deal, DealCommand command) {
        Long seen = switch (command) {
            case PlaceBid c -> c.version();
            case WithdrawBid c -> c.version();
            case PostOffer c -> c.version();
            case AcceptBid c -> c.version();
            case AcceptOffer c -> c.version();
            case Cancel c -> null;
            case Tick c -> null;
        };
        if (seen != null && seen != deal.version()) {
            return reject(deal, ErrorCode.VERSION_CONFLICT,
                    "거래가 갱신되었습니다(현재 version " + deal.version() + "). 다시 불러오세요");
        }
        return null;
    }

    // --- commands --------------------------------------------------------------------------

    /** R2 band, R1 against this driver's own last bid (kept across withdrawals), R5 replace. */
    private Result placeBid(Deal deal, PlaceBid c, Instant now) {
        DealRules.PriceBand band = rules.band(deal.basePrice());
        if (!band.contains(c.price())) {
            return reject(deal, ErrorCode.OUT_OF_BAND, outOfBand(band));
        }
        Double last = deal.lastBidByDriver().get(c.driverId());
        if (last != null && c.price() > last) {
            return reject(deal, ErrorCode.PRICE_NOT_CONCEDED,
                    "직전 호가(" + fmt(last) + ")보다 높은 가격은 제출할 수 없습니다");
        }

        double pickupKm = Geo.haversineKm(c.driverLat(), c.driverLng(), deal.originLat(), deal.originLng());
        // A replaced bid gets a new id, so a rider cannot accept a price they never saw.
        Deal.Bid bid = new Deal.Bid(String.format("B-%03d", deal.nextBidSeq()), c.driverId(), c.price(),
                c.driverLat(), c.driverLng(), pickupKm, rules.pickupEtaMin(pickupKm), now);
        boolean replacing = deal.bids().stream().anyMatch(b -> b.driverId().equals(c.driverId()));

        Draft d = new Draft(deal);
        d.bids.removeIf(b -> b.driverId().equals(c.driverId()));
        d.bids.add(bid);
        d.lastBidByDriver.put(c.driverId(), c.price());
        d.nextBidSeq++;
        d.status = DealStatus.NEGOTIATING;
        d.pendingSide = PendingSide.RIDER;
        d.round++;
        d.version++;
        Deal next = d.build();

        Double lowest = lowest(next);
        DealEvent event = replacing
                ? new BidUpdated(next.dealId(), bid, lowest, next.bids().size(), next.pendingSide(), next.round(), next.version())
                : new BidPlaced(next.dealId(), bid, lowest, next.bids().size(), next.pendingSide(), next.round(), next.version());
        return new Result.Accepted(next, List.of(event));
    }

    /** R5: drop this driver's live bid. Not a round (R8); the driver's last price still binds R1. */
    private Result withdrawBid(Deal deal, WithdrawBid c) {
        Deal.Bid bid = deal.bids().stream().filter(b -> b.driverId().equals(c.driverId())).findFirst().orElse(null);
        if (bid == null) {
            return reject(deal, ErrorCode.BID_NOT_FOUND, "철회할 호가가 없습니다");
        }
        Draft d = new Draft(deal);
        d.bids.remove(bid);
        d.withdrawCount++;
        d.version++;
        Deal next = d.build();
        return new Result.Accepted(next, List.of(new BidWithdrawn(next.dealId(), bid.bidId(), bid.driverId(),
                WithdrawReason.BY_DRIVER, lowest(next), next.bids().size(), next.round(), next.version())));
    }

    /** R2 band, R1 against the rider's own last offer. The offer lives for the offer TTL (R6). */
    private Result postOffer(Deal deal, PostOffer c, Instant now) {
        DealRules.PriceBand band = rules.band(deal.basePrice());
        if (!band.contains(c.price())) {
            return reject(deal, ErrorCode.OUT_OF_BAND, outOfBand(band));
        }
        if (deal.lastOfferPrice() != null && c.price() < deal.lastOfferPrice()) {
            return reject(deal, ErrorCode.PRICE_NOT_CONCEDED,
                    "직전 오퍼(" + fmt(deal.lastOfferPrice()) + ")보다 낮은 가격은 제출할 수 없습니다");
        }
        Draft d = new Draft(deal);
        d.offer = new Deal.RiderOffer(c.price(), now, now.plus(rules.offerTtl()));
        d.lastOfferPrice = c.price();
        d.status = DealStatus.NEGOTIATING;
        d.pendingSide = PendingSide.DRIVER;
        d.round++;
        d.version++;
        Deal next = d.build();
        return new Result.Accepted(next, List.of(new OfferPosted(next.dealId(), c.price(), next.offer().expiresAt(),
                next.pendingSide(), next.round(), next.version())));
    }

    /** R12: the rider may cancel any time before a match; every live bid and the offer go with it. */
    private Result cancel(Deal deal) {
        Draft d = new Draft(deal);
        d.bids.clear();
        d.offer = null;
        d.status = DealStatus.CANCELLED;
        d.endReason = EndReason.CANCELLED_BY_RIDER;
        d.version++;
        Deal next = d.build();
        return new Result.Accepted(next, List.of(new DealExpired(next.dealId(), EndReason.CANCELLED_BY_RIDER, next.version())));
    }

    // --- helpers ---------------------------------------------------------------------------

    private static Result reject(Deal deal, ErrorCode code, String message) {
        return new Result.Rejected(code, message, deal.version());
    }

    private static Double lowest(Deal deal) {
        return deal.lowestBidPrice().isPresent() ? deal.lowestBidPrice().getAsDouble() : null;
    }

    private static String outOfBand(DealRules.PriceBand band) {
        return "허용 가격 범위(" + fmt(band.min()) + " ~ " + fmt(band.max()) + ")를 벗어났습니다";
    }

    private static String fmt(double price) {
        return String.format("%.1f", price);
    }

    /** Mutable copy of a Deal used while one command is applied; build() returns the new snapshot. */
    private static final class Draft {
        private final Deal base;
        final List<Deal.Bid> bids;
        final Map<String, Double> lastBidByDriver;
        DealStatus status;
        PendingSide pendingSide;
        int round;
        long version;
        Deal.RiderOffer offer;
        Double lastOfferPrice;
        int withdrawCount;
        int nextBidSeq;
        Deal.Match match;
        EndReason endReason;

        Draft(Deal d) {
            base = d;
            bids = new ArrayList<>(d.bids());
            lastBidByDriver = new HashMap<>(d.lastBidByDriver());
            status = d.status();
            pendingSide = d.pendingSide();
            round = d.round();
            version = d.version();
            offer = d.offer();
            lastOfferPrice = d.lastOfferPrice();
            withdrawCount = d.withdrawCount();
            nextBidSeq = d.nextBidSeq();
            match = d.match();
            endReason = d.endReason();
        }

        Deal build() {
            return new Deal(base.dealId(), base.riderId(), base.originLat(), base.originLng(), base.basePrice(),
                    base.createdAt(), base.expiresAt(), status, pendingSide, round, version, bids, lastBidByDriver,
                    offer, lastOfferPrice, withdrawCount, nextBidSeq, match, endReason);
        }
    }
}
