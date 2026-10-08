-- presence_remove.lua: 가상 인구의 접속 종료 (R5, api-spec §6.6·§6.7).
-- 참여 중(§1.5)이면 아무것도 하지 않는다. 아니면 sweep.lua 3단계와 같이 지운다.
-- ARGV: nowMs, actorType(DRIVER|RIDER), actorId
local nowMs = tonumber(ARGV[1])
local actorType = ARGV[2]
local actorId = ARGV[3]

if engaged(actorType, actorId, nowMs) then
    return cjson.encode({ ok = true, removed = false })
end
remove_presence(actorType, actorId)
return cjson.encode({ ok = true, removed = true })
