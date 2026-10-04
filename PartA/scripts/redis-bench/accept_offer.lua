-- R10 이중 체결 차단 로직만 분리한 벤치마크용 스크립트.
-- 실제 accept_offer.lua라면 status/version 검증(R9)도 포함되지만,
-- 여기서는 "기사가 걸어둔 활성 호가 수(N)가 늘어날 때 정리 루프 비용이 어떻게 변하는가"만 측정한다.
--
-- KEYS[1] = driver:{driverId}:deals   (그 기사가 호가를 걸어둔 dealId Set)
-- ARGV[1] = driverId
-- ARGV[2] = 방금 체결된 dealId (정리 대상에서 제외)

local t1 = redis.call('TIME')

local otherDeals = redis.call('SMEMBERS', KEYS[1])
local cleaned = 0
for _, d in ipairs(otherDeals) do
    if d ~= ARGV[2] then
        redis.call('HDEL', 'deal:' .. d .. ':bids', ARGV[1])
        cleaned = cleaned + 1
    end
end

local t2 = redis.call('TIME')
local elapsedMicros = (tonumber(t2[1]) - tonumber(t1[1])) * 1000000 + (tonumber(t2[2]) - tonumber(t1[2]))

return {elapsedMicros, cleaned}
