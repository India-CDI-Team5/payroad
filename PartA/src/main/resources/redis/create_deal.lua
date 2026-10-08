-- create_deal.lua: 거래 생성과 승객 presence 등록 (R4, R7). api-spec §4.1, §6.1.
-- ARGV: nowMs, dealId, riderId, originLat, originLng, basePrice, dealTtlMs, offerTtlMs, roundLimit,
--       bandMinRatio, bandMaxRatio, avgSpeedKmh, detourFactor, maxActiveBids, presenceTtlMs, metaJson
local nowMs = tonumber(ARGV[1])
local dealId = ARGV[2]
local riderId = ARGV[3]
local originLat = tonumber(ARGV[4])
local originLng = tonumber(ARGV[5])
local basePrice = tonumber(ARGV[6])
local dealTtlMs = tonumber(ARGV[7])
local offerTtlMs = tonumber(ARGV[8])
local roundLimit = tonumber(ARGV[9])
local bandMinRatio = tonumber(ARGV[10])
local bandMaxRatio = tonumber(ARGV[11])
local avgSpeedKmh = tonumber(ARGV[12])
local detourFactor = tonumber(ARGV[13])
local maxActiveBids = tonumber(ARGV[14])
local presenceTtlMs = tonumber(ARGV[15])
local metaJson = ARGV[16]

local expiresAt = nowMs + dealTtlMs
local purgeAt = nowMs + 300000

redis.call('HSET', deal_key(dealId),
        'dealId', dealId,
        'riderId', riderId,
        'originLat', num(originLat),
        'originLng', num(originLng),
        'basePrice', num(basePrice),
        'bandMin', num(basePrice * bandMinRatio),
        'bandMax', num(basePrice * bandMaxRatio),
        'status', 'OPEN',
        'pendingSide', 'DRIVER',
        'round', '0',
        'version', '1',
        'withdrawCount', '0',
        'nextBidSeq', '1',
        'createdAt', int(nowMs),
        'expiresAt', int(expiresAt),
        'purgeAt', int(purgeAt),
        'offerTtlMs', int(offerTtlMs),
        'roundLimit', int(roundLimit),
        'avgSpeedKmh', num(avgSpeedKmh),
        'detourFactor', num(detourFactor),
        'maxActiveBids', int(maxActiveBids),
        'meta', metaJson)

redis.call('ZADD', 'deals:expiry', int(expiresAt), dealId)
redis.call('ZADD', 'deals:purge', int(purgeAt), dealId)
redis.call('GEOADD', 'geo:deals', num(originLng), num(originLat), dealId)

-- 거래를 만든 승객은 presence가 자동 등록된다(§4.1). 위치는 출발지.
local riderKey = 'presence:rider:' .. riderId
redis.call('HSET', riderKey, 'expiresAt', int(nowMs + presenceTtlMs), 'activeDealId', dealId)
redis.call('ZADD', 'presence:expiry', int(nowMs + presenceTtlMs), 'R:' .. riderId)
redis.call('GEOADD', 'geo:riders', num(originLng), num(originLat), riderId)

return reply_ok(new_out())
