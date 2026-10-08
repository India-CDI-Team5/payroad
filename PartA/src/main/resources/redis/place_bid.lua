-- place_bid.lua: 기사 호가 제출·갱신 (R1, R2, R5, R8, R11, R13). api-spec §6.6.
-- ARGV: nowMs, dealId, driverId, price, driverLat, driverLng, version
local nowMs = tonumber(ARGV[1])
local dealId = ARGV[2]
local driverId = arg_or_nil(ARGV[3])
local price = tonumber(ARGV[4])
local driverLat = tonumber(ARGV[5])
local driverLng = tonumber(ARGV[6])
local version = arg_or_nil(ARGV[7])

local deal = load_deal(dealId)
local refused = check_common(deal, nowMs, 'DRIVER', driverId, version, true)
if refused then return refused end

-- R2
if price < deal.bandMin or price > deal.bandMax then
    return out_of_band(deal)
end
-- R1: 자기 직전 호가(철회 후에도 유지)보다 높을 수 없다.
local last = redis.call('HGET', last_bid_key(dealId), driverId)
if last and price > tonumber(last) then
    return reply_err('PRICE_NOT_CONCEDED', '직전 호가(' .. fmt1(tonumber(last)) .. ')보다 높은 가격은 제출할 수 없습니다',
            deal.version)
end
-- R13: 이 거래에 살아 있는 호가가 없을 때만 건수를 본다.
local setKey = driver_deals_key(driverId)
if redis.call('SISMEMBER', setKey, dealId) == 0 and redis.call('SCARD', setKey) >= deal.maxActiveBids then
    return reply_err('MAX_ACTIVE_BIDS_EXCEEDED',
            '동시에 호가할 수 있는 거래는 최대 ' .. int(deal.maxActiveBids) .. '건입니다', deal.version)
end

local out = new_out()
-- R8
if deal.round >= deal.roundLimit then
    return round_limit(deal, nowMs, out)
end

-- §6.2: 픽업 거리·ETA는 제출 시점 좌표로 계산한다.
local pickupKm = haversine_km(driverLat, driverLng, deal.originLat, deal.originLng)
local pickupEta = pickupKm / deal.avgSpeedKmh * 60 * deal.detourFactor
local seq = deal.nextBidSeq
-- 대체된 호가는 새 bidId를 받는다(승객이 보지 못한 가격을 수락하지 않게).
local bid = {
    bidId = string.format('B-%03d', seq), driverId = driverId, price = num(price),
    driverLat = num(driverLat), driverLng = num(driverLng),
    pickupDistanceKm = num(pickupKm), pickupEtaMin = num(pickupEta),
    createdAt = nowMs, seq = seq,
}
local replacing = redis.call('HEXISTS', bids_key(dealId), driverId) == 1

redis.call('HSET', bids_key(dealId), driverId, cjson.encode(bid))
redis.call('HSET', last_bid_key(dealId), driverId, num(price))
redis.call('HSET', deal_key(dealId), 'nextBidSeq', int(seq + 1), 'status', 'NEGOTIATING', 'pendingSide', 'RIDER',
        'round', int(deal.round + 1))
local newVersion = redis.call('HINCRBY', deal_key(dealId), 'version', 1)
redis.call('SADD', setKey, dealId)

local name = 'bid.placed'
if replacing then name = 'bid.updated' end
emit(out, ev_bid(name, dealId, bid, lowest_price(dealId), redis.call('HLEN', bids_key(dealId)), 'RIDER',
        deal.round + 1, newVersion))
return reply_ok(out)
