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
import com.cdi.dynamicpayroad.domain.DealEvent.DealMatched;
import com.cdi.dynamicpayroad.domain.DealEvent.OfferExpired;
import com.cdi.dynamicpayroad.domain.DealEvent.OfferPosted;
import com.cdi.dynamicpayroad.domain.Enums.EndReason;
import com.cdi.dynamicpayroad.domain.Enums.MatchPath;
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
 * <p>R9 (one match only) holds because a MATCHED deal rejects every later accept; making
 * concurrent callers see each other's result is the caller's job (one lock per market).
 * A deal past its TTL rejects actions even before the next {@link Tick} marks it EXPIRED.
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

    public Result apply(Deal deal, DealCommand command, DriverAvailability drivers, Instant now) {
        if (!deal.status().isActive()) {
            if (command instanceof Tick) return new Result.Accepted(deal, List.of());
            return deal.status() == DealStatus.MATCHED
                    ? reject(deal, ErrorCode.DEAL_ALREADY_MATCHED, "이미 체결된 거래입니다")
                    : reject(deal, ErrorCode.DEAL_NOT_ACTIVE, "종료된 거래입니다");
        }

        if (!(command instanceof Tick) && !now.isBefore(deal.expiresAt())) {
            return reject(deal, ErrorCode.DEAL_NOT_ACTIVE, "거래 시간이 만료되었습니다");
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
            case AcceptBid c -> acceptBid(deal, c, now);
            case AcceptOffer c -> acceptOffer(deal, c, now);
            case Tick c -> tick(deal, now);
        };
    }

    /**
     * Pull one driver's live bid out of a deal for a reason other than the driver asking
     * (R10 matched elsewhere, R5 disconnected). Not a round (R8) and not counted in
     * withdrawCount, which measures voluntary withdrawals. Returns the deal unchanged, with no
     * events, when the driver has no live bid there.
     */
    public Result.Accepted forceWithdraw(Deal deal, String driverId, WithdrawReason reason) {
        Deal.Bid bid = deal.bids().stream().filter(b -> b.driverId().equals(driverId)).findFirst().orElse(null);
        if (bid == null || !deal.status().isActive()) return new Result.Accepted(deal, List.of());
        Draft d = new Draft(deal);
        d.bids.remove(bid);
        d.version++;
        Deal next = d.build();
        return new Result.Accepted(next, List.of(new BidWithdrawn(next.dealId(), bid.bidId(), driverId, reason,
                lowest(next), next.bids().size(), next.round(), next.version())));
    }

    // --- common checks ---------------------------------------------------------------------

    /** R11: riders act only on their own deal; drivers only while available. A missing id never passes. */
    private Result checkActor(Deal deal, DealCommand command, DriverAvailability drivers) {
        boolean riderCommand = command instanceof PostOffer || command instanceof AcceptBid || command instanceof Cancel;
        String rider = switch (command) {
            case PostOffer c -> c.riderId();
            case AcceptBid c -> c.riderId();
            case Cancel c -> c.riderId();
            default -> null;
        };
        if (riderCommand && !deal.riderId().equals(rider)) {
            return reject(deal, ErrorCode.NOT_DEAL_OWNER, "본인의 거래가 아닙니다");
        }
        boolean driverCommand = command instanceof PlaceBid || command instanceof WithdrawBid || command instanceof AcceptOffer;
        String driver = switch (command) {
            case PlaceBid c -> c.driverId();
            case WithdrawBid c -> c.driverId();
            case AcceptOffer c -> c.driverId();
            default -> null;
        };
        if (driverCommand && (driver == null || !drivers.isAvailable(driver))) {
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

        if (deal.round() >= rules.roundLimit()) {
            return expire(deal, EndReason.ROUND_LIMIT);
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
        if (deal.round() >= rules.roundLimit()) {
            return expire(deal, EndReason.ROUND_LIMIT);
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

    /** R3 path A: the rider picks any live bid; that driver wins at that bid's price. */
    private Result acceptBid(Deal deal, AcceptBid c, Instant now) {
        List<Deal.Bid> ranked = deal.bidsAscending();
        int index = -1;
        for (int i = 0; i < ranked.size(); i++) {
            if (ranked.get(i).bidId().equals(c.bidId())) index = i;
        }
        if (index < 0) {
            return reject(deal, ErrorCode.BID_NOT_FOUND, "지목한 호가가 없거나 철회되었습니다");
        }
        Deal.Bid chosen = ranked.get(index);
        Deal.Bid cheapest = ranked.get(0);
        Deal.Match match = new Deal.Match(chosen.driverId(), chosen.price(), MatchPath.RIDER_PICKED_BID, index + 1,
                cheapest.price(), chosen.pickupDistanceKm(), chosen.pickupEtaMin(),
                cheapest.pickupDistanceKm(), cheapest.pickupEtaMin(), now);
        return matched(deal, match);
    }

    /** R3 path B, R6: the first available driver to take a live rider offer wins at the offer price. */
    private Result acceptOffer(Deal deal, AcceptOffer c, Instant now) {
        Deal.RiderOffer offer = deal.offer();
        if (offer == null) {
            return reject(deal, ErrorCode.OFFER_NOT_FOUND, "수락할 승객 오퍼가 없습니다");
        }
        if (!now.isBefore(offer.expiresAt())) {
            return reject(deal, ErrorCode.OFFER_EXPIRED, "승객 오퍼가 만료되었습니다");
        }
        Deal.Bid own = deal.bids().stream().filter(b -> b.driverId().equals(c.driverId())).findFirst().orElse(null);
        List<Deal.Bid> ranked = deal.bidsAscending();
        Deal.Bid cheapest = ranked.isEmpty() ? null : ranked.get(0);
        Deal.Match match = new Deal.Match(c.driverId(), offer.price(), MatchPath.DRIVER_TOOK_OFFER, 0,
                cheapest == null ? null : cheapest.price(),
                own == null ? null : own.pickupDistanceKm(), own == null ? null : own.pickupEtaMin(),
                cheapest == null ? null : cheapest.pickupDistanceKm(),
                cheapest == null ? null : cheapest.pickupEtaMin(), now);
        return matched(deal, match);
    }

    /** R7 deal TTL first, then R6 offer TTL. Nothing due means no change and no events. */
    private Result tick(Deal deal, Instant now) {
        if (!now.isBefore(deal.expiresAt())) {
            return expire(deal, EndReason.TTL);
        }
        if (deal.offer() != null && !now.isBefore(deal.offer().expiresAt())) {
            Draft d = new Draft(deal);
            d.offer = null;
            d.pendingSide = PendingSide.RIDER;
            d.version++;
            Deal next = d.build();
            return new Result.Accepted(next, List.of(new OfferExpired(next.dealId(), next.pendingSide(), next.round(), next.version())));
        }
        return new Result.Accepted(deal, List.of());
    }

    private Result matched(Deal deal, Deal.Match match) {
        Draft d = new Draft(deal);
        d.status = DealStatus.MATCHED;
        d.match = match;
        d.offer = null;
        d.version++;
        Deal next = d.build();
        return new Result.Accepted(next, List.of(new DealMatched(next.dealId(), match, next.version())));
    }

    /** Close without a match (R7 TTL, R8 round limit). Live bids and the offer lapse with it. */
    private Result expire(Deal deal, EndReason reason) {
        Draft d = new Draft(deal);
        d.bids.clear();
        d.offer = null;
        d.status = DealStatus.EXPIRED;
        d.endReason = reason;
        d.version++;
        Deal next = d.build();
        return new Result.Accepted(next, List.of(new DealExpired(next.dealId(), reason, next.version())));
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
