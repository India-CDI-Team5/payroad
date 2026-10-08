-- accept_bid.lua: 승객 지목 수락 (R3, R9, R10). 체결과 R10 정리를 이 스크립트 한 번에 끝낸다.
-- ARGV: nowMs, dealId, riderId, bidId, version
local nowMs = tonumber(ARGV[1])
local dealId = ARGV[2]
local riderId = arg_or_nil(ARGV[3])
local bidId = ARGV[4]
local version = arg_or_nil(ARGV[5])

local deal = load_deal(dealId)
local refused = check_common(deal, nowMs, 'RIDER', riderId, version, true)
if refused then return refused end

-- 순위 = 살아 있는 호가의 (가격, seq) 오름차순. chosenRank = 지목 호가의 순위, 비교군 = 1위 호가.
local ranked = ranked_bids(dealId)
local index = nil
for i, b in ipairs(ranked) do
    if b.bidId == bidId then index = i end
end
if not index then
    return reply_err('BID_NOT_FOUND', '지목한 호가가 없거나 철회되었습니다', deal.version)
end
local chosen = ranked[index]
local cheapest = ranked[1]

local out = new_out()
match_deal(deal, {
    driverId = chosen.driverId,
    finalPrice = tonumber(chosen.price),
    matchPath = 'RIDER_PICKED_BID',
    chosenRank = index,
    lowestBidPrice = tonumber(cheapest.price),
    pickupDistanceKm = tonumber(chosen.pickupDistanceKm),
    pickupEtaMin = tonumber(chosen.pickupEtaMin),
    lowestBidPickupDistanceKm = tonumber(cheapest.pickupDistanceKm),
    lowestBidPickupEtaMin = tonumber(cheapest.pickupEtaMin),
    matchedAt = nowMs,
}, nowMs, out)
return reply_ok(out)
