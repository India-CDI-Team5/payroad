-- 벤치마크용 데이터 시딩 스크립트. 기사 한 명이 N개의 거래에 호가를 걸어둔 상태를 재현한다.
--
-- KEYS[1] = driver:{driverId}:deals
-- ARGV[1] = N (시딩할 거래 수)
-- ARGV[2] = driverId

local n = tonumber(ARGV[1])
for i = 1, n do
    local dealId = 'D-' .. i
    redis.call('SADD', KEYS[1], dealId)
    redis.call('HSET', 'deal:' .. dealId .. ':bids', ARGV[2], '{"price":100}')
end

return 'seeded:' .. n
