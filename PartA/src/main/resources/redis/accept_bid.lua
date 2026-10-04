-- 승객이 특정 기사의 호가를 지목 수락 (R9 단일 체결 원자성, R10 기사 이중 체결 차단)
-- KEYS[1] = nego:deal:{dealId}             (Hash: status, riderId, basePrice, version)
-- KEYS[2] = nego:driver:{driverId}:deals    (Set: 이 기사가 호가를 낸 dealId 집합)
-- ARGV[1] = driverId (지목된 기사)
-- ARGV[2] = dealId

local status = redis.call('HGET', KEYS[1], 'status')
if status ~= 'NEGOTIATING' then
    return redis.error_reply('DEAL_ALREADY_MATCHED')
end

local bidExists = redis.call('HEXISTS', 'nego:deal:' .. ARGV[2] .. ':bids', ARGV[1])
if bidExists == 0 then
    return redis.error_reply('BID_NOT_FOUND')
end

redis.call('HSET', KEYS[1], 'status', 'MATCHED')
redis.call('HSET', KEYS[1], 'matchedDriver', ARGV[1])
local version = redis.call('HINCRBY', KEYS[1], 'version', 1)

-- R10: 이 기사가 다른 거래에 걸어둔 호가를 전부 원자적으로 철회.
-- lastBid는 R1(철회로 가격 단조성 제약을 리셋 못 함) 때문에 일부러 남긴다.
-- 각 거래의 version은 올려줘야 그 거래를 보던 클라이언트가 "호가가 사라졌다"는
-- 변경을 감지하고 화면을 갱신한다(안 올리면 유령 호가가 남음).
local otherDeals = redis.call('SMEMBERS', KEYS[2])
local cleaned = 0
for _, d in ipairs(otherDeals) do
    if d ~= ARGV[2] then
        redis.call('HDEL', 'nego:deal:' .. d .. ':bids', ARGV[1])
        redis.call('ZREM', 'nego:deal:' .. d .. ':bidsByPrice', ARGV[1])
        redis.call('HINCRBY', 'nego:deal:' .. d, 'version', 1)
        cleaned = cleaned + 1
    end
end
redis.call('DEL', KEYS[2])

return {'MATCHED', tostring(version), tostring(cleaned)}
