-- 기사 호가 등록 (R1 가격 단조성, R13 기사당 동시 활성 호가 상한)
-- KEYS[1] = nego:deal:{dealId}                 (Hash: status, riderId, basePrice, version)
-- KEYS[2] = nego:deal:{dealId}:bids             (Hash: driverId -> price)
-- KEYS[3] = nego:deal:{dealId}:bidsByPrice      (ZSet: score=price, member=driverId)
-- KEYS[4] = nego:deal:{dealId}:lastBid          (Hash: driverId -> 직전 가격, 철회해도 유지)
-- KEYS[5] = nego:driver:{driverId}:deals        (Set: 이 기사가 호가를 낸 dealId 집합)
-- ARGV[1] = driverId
-- ARGV[2] = price
-- ARGV[3] = dealId
-- ARGV[4] = maxActiveBids (R13 상한, 기본 50)

local status = redis.call('HGET', KEYS[1], 'status')
if not status then
    return redis.error_reply('DEAL_NOT_FOUND')
end
if status == 'MATCHED' or status == 'EXPIRED' or status == 'CANCELLED' then
    return redis.error_reply('DEAL_NOT_ACTIVE')
end

-- R1: 자신의 직전 호가보다 낮거나 같아야 함
local lastPrice = redis.call('HGET', KEYS[4], ARGV[1])
if lastPrice and tonumber(ARGV[2]) > tonumber(lastPrice) then
    return redis.error_reply('PRICE_NOT_CONCEDED')
end

-- R13: 이 거래에 처음 거는 호가일 때만 상한 검사 (같은 거래 재호가는 카운트 중복 방지)
local alreadyBidding = redis.call('HEXISTS', KEYS[2], ARGV[1])
if alreadyBidding == 0 then
    local activeCount = redis.call('SCARD', KEYS[5])
    if activeCount >= tonumber(ARGV[4]) then
        return redis.error_reply('MAX_ACTIVE_BIDS_EXCEEDED')
    end
end

redis.call('HSET', KEYS[2], ARGV[1], ARGV[2])
redis.call('ZADD', KEYS[3], ARGV[2], ARGV[1])
redis.call('HSET', KEYS[4], ARGV[1], ARGV[2])
redis.call('SADD', KEYS[5], ARGV[3])
redis.call('HSET', KEYS[1], 'status', 'NEGOTIATING')
local version = redis.call('HINCRBY', KEYS[1], 'version', 1)

return {'OK', tostring(version)}
