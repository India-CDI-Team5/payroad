-- presence_upsert.lua: 기사·승객 등록과 heartbeat (R5, R11). api-spec §4.5~§4.7.
-- 활성 호가의 픽업 거리는 바꾸지 않는다(v1.3).
-- ARGV: nowMs, actorType(DRIVER|RIDER), actorId, ttlMs, lat, lng (lat·lng는 "" 가능)
local nowMs = tonumber(ARGV[1])
local actorType = ARGV[2]
local actorId = ARGV[3]
local ttlMs = tonumber(ARGV[4])
local lat = arg_or_nil(ARGV[5])
local lng = arg_or_nil(ARGV[6])

local isDriver = actorType == 'DRIVER'
local key, member
if isDriver then
    key = 'presence:driver:' .. actorId
    member = 'D:' .. actorId
else
    key = 'presence:rider:' .. actorId
    member = 'R:' .. actorId
end

local hasPosition = lat ~= nil and lng ~= nil
if isDriver and not hasPosition and redis.call('EXISTS', key) == 0 then
    return reply_err('DRIVER_NOT_AVAILABLE', '기사 위치가 필요합니다', 0)
end

local expiresAt = nowMs + ttlMs
redis.call('HSET', key, 'expiresAt', int(expiresAt))
redis.call('ZADD', 'presence:expiry', int(expiresAt), member)

local matched = isDriver and redis.call('HGET', driver_state_key(actorId), 'status') == 'MATCHED'
if hasPosition then
    local latS, lngS = num(tonumber(lat)), num(tonumber(lng))
    redis.call('HSET', key, 'lat', latS, 'lng', lngS)
    if isDriver then
        if not matched then redis.call('GEOADD', 'geo:drivers', lngS, latS, actorId) end
    else
        redis.call('GEOADD', 'geo:riders', lngS, latS, actorId)
    end
end

local status = 'ONLINE'
if matched then status = 'MATCHED' end
return cjson.encode({ ok = true, status = status, expiresAt = expiresAt })
