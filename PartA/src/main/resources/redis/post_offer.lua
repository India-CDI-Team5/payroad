-- post_offer.lua: 승객 오퍼 게시·갱신 (R1, R2, R6, R8, R11). api-spec §6.6.
-- ARGV: nowMs, dealId, riderId, price, version
local nowMs = tonumber(ARGV[1])
local dealId = ARGV[2]
local riderId = arg_or_nil(ARGV[3])
local price = tonumber(ARGV[4])
local version = arg_or_nil(ARGV[5])

local deal = load_deal(dealId)
local refused = check_common(deal, nowMs, 'RIDER', riderId, version, true)
if refused then return refused end

-- R2
if price < deal.bandMin or price > deal.bandMax then
    return out_of_band(deal)
end
-- R1: 자기 직전 오퍼보다 낮을 수 없다.
if deal.lastOfferPrice and price < deal.lastOfferPrice then
    return reply_err('PRICE_NOT_CONCEDED',
            '직전 오퍼(' .. fmt1(deal.lastOfferPrice) .. ')보다 낮은 가격은 제출할 수 없습니다', deal.version)
end

local out = new_out()
-- R8
if deal.round >= deal.roundLimit then
    return round_limit(deal, nowMs, out)
end

-- R6: 오퍼는 offerTtlMs 동안 산다.
local expiresAt = nowMs + deal.offerTtlMs
redis.call('HSET', deal_key(dealId), 'offerPrice', num(price), 'offerCreatedAt', int(nowMs),
        'offerExpiresAt', int(expiresAt), 'lastOfferPrice', num(price), 'status', 'NEGOTIATING',
        'pendingSide', 'DRIVER', 'round', int(deal.round + 1))
local newVersion = redis.call('HINCRBY', deal_key(dealId), 'version', 1)
redis.call('ZADD', 'offers:expiry', int(expiresAt), dealId)

emit(out, ev_offer_posted(dealId, price, expiresAt, 'DRIVER', deal.round + 1, newVersion))
return reply_ok(out)
