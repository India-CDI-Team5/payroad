-- accept_offer.lua: 기사 선착 수락 (R3, R6, R9, R10, R11). 체결과 R10 정리를 이 스크립트 한 번에 끝낸다.
-- ARGV: nowMs, dealId, driverId, version
local nowMs = tonumber(ARGV[1])
local dealId = ARGV[2]
local driverId = arg_or_nil(ARGV[3])
local version = arg_or_nil(ARGV[4])

local deal = load_deal(dealId)
local refused = check_common(deal, nowMs, 'DRIVER', driverId, version, true)
if refused then return refused end

if not deal.offerPrice then
    return reply_err('OFFER_NOT_FOUND', '수락할 승객 오퍼가 없습니다', deal.version)
end
-- R6: 스윕 전이라도 만료 시각이 지났으면 거부.
if nowMs >= deal.offerExpiresAt then
    return reply_err('OFFER_EXPIRED', '승객 오퍼가 만료되었습니다', deal.version)
end

-- 승자 픽업 = 그 기사의 이 거래 호가(없으면 null), 비교군 = 1위 호가(없으면 null).
local own = nil
local raw = redis.call('HGET', bids_key(dealId), driverId)
if raw then own = cjson.decode(raw) end
local ranked = ranked_bids(dealId)
local cheapest = ranked[1]

local m = {
    driverId = driverId,
    finalPrice = deal.offerPrice,
    matchPath = 'DRIVER_TOOK_OFFER',
    chosenRank = 0,
    matchedAt = nowMs,
}
if own then
    m.pickupDistanceKm = tonumber(own.pickupDistanceKm)
    m.pickupEtaMin = tonumber(own.pickupEtaMin)
end
if cheapest then
    m.lowestBidPrice = tonumber(cheapest.price)
    m.lowestBidPickupDistanceKm = tonumber(cheapest.pickupDistanceKm)
    m.lowestBidPickupEtaMin = tonumber(cheapest.pickupEtaMin)
end

local out = new_out()
match_deal(deal, m, nowMs, out)
return reply_ok(out)
