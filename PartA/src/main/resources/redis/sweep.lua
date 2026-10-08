-- sweep.lua: 만료·정리 (api-spec §6.5). 각 단계는 시각 오름차순 → 같으면 member 사전순(ZSet 순서).
-- ARGV: nowMs, limit(단계별 최대 처리 건수), presenceTtlMs
local nowMs = tonumber(ARGV[1])
local limit = ARGV[2]
local now = int(nowMs)

local out = new_out()

-- 1단계: 거래 TTL (R7). 활성 호가가 있어도 만료된다.
local due = redis.call('ZRANGEBYSCORE', 'deals:expiry', '-inf', now, 'LIMIT', 0, limit)
for _, dealId in ipairs(due) do
    local deal = load_deal(dealId)
    if deal and is_active(deal) then
        close_deal(deal, 'EXPIRED', 'TTL', nowMs, out)
    else
        redis.call('ZREM', 'deals:expiry', dealId)
    end
end

-- 2단계: 승객 오퍼 TTL (R6). 오퍼 제거, pendingSide = RIDER. 어느 경우든 offers:expiry에서 뺀다.
due = redis.call('ZRANGEBYSCORE', 'offers:expiry', '-inf', now, 'LIMIT', 0, limit)
for _, dealId in ipairs(due) do
    local deal = load_deal(dealId)
    if deal and is_active(deal) and deal.offerPrice then
        remove_offer(dealId)
        redis.call('HSET', deal_key(dealId), 'pendingSide', 'RIDER')
        local version = redis.call('HINCRBY', deal_key(dealId), 'version', 1)
        emit(out, ev_offer_expired(dealId, 'RIDER', deal.round, version))
    end
    redis.call('ZREM', 'offers:expiry', dealId)
end

-- 3단계: presence 정리 (R5). 참여 중(§1.5)이면 지우지 않고 점수만 nowMs + presenceTtlMs로 미룬다
-- (같은 사람을 스윕마다 다시 읽지 않게). 아니면 presence 해시·presence:expiry·GEO 위치를 지운다.
-- 이탈을 이유로 호가를 철회하거나 거래를 취소하지 않는다.
local presenceTtlMs = tonumber(ARGV[3])
due = redis.call('ZRANGEBYSCORE', 'presence:expiry', '-inf', now, 'LIMIT', 0, limit)
for _, member in ipairs(due) do
    local actorType = 'RIDER'
    if string.sub(member, 1, 2) == 'D:' then actorType = 'DRIVER' end
    local actorId = string.sub(member, 3)
    if engaged(actorType, actorId, nowMs) then
        redis.call('ZADD', 'presence:expiry', int(nowMs + presenceTtlMs), member)
    else
        remove_presence(actorType, actorId)
    end
end

-- 4단계: 물리 삭제 (createdAt + 300초). 활성이면 먼저 EXPIRED(TTL)로 닫고, MATCHED면 승자를 복귀시킨다
-- (운행 완료 가정).
due = redis.call('ZRANGEBYSCORE', 'deals:purge', '-inf', now, 'LIMIT', 0, limit)
for _, dealId in ipairs(due) do
    local deal = load_deal(dealId)
    if deal then
        if is_active(deal) then
            close_deal(deal, 'EXPIRED', 'TTL', nowMs, out)
        elseif deal.status == 'MATCHED' and deal.matchDriverId then
            local winner = deal.matchDriverId
            if redis.call('HGET', driver_state_key(winner), 'dealId') == dealId then
                redis.call('DEL', driver_state_key(winner))
                local presence = 'presence:driver:' .. winner
                local exp = redis.call('HGET', presence, 'expiresAt')
                if exp and tonumber(exp) > nowMs then
                    local pos = redis.call('HMGET', presence, 'lat', 'lng')
                    if pos[1] and pos[2] then
                        redis.call('GEOADD', 'geo:drivers', pos[2], pos[1], winner)
                    end
                end
            end
        end
        redis.call('DEL', deal_key(dealId), bids_key(dealId), last_bid_key(dealId))
    end
    redis.call('ZREM', 'deals:purge', dealId)
end

return reply_ok(out)
