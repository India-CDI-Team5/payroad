-- lib/common.lua: LuaScripts가 모든 스크립트 앞에 이어 붙이는 공용 함수 (api-spec v1.3 §6.6).
-- 규칙: KEYS는 비우고 ARGV[1]은 nowMs. Redis 시계·난수·키 TTL을 쓰지 않는다(호출 규약).
-- SMEMBERS·HGETALL 결과는 정렬한 뒤 순회한다(같은 입력 → 같은 바이트).

-- 실수는 '%.17g' 문자열로 저장·반환한다(tostring은 14자리라 값이 바뀐다).
local function num(x)
    return string.format('%.17g', x)
end

-- 정수(version, round, 시각 ms)를 Redis에 쓸 때. 숫자 인자는 '%.14g'로 바뀌므로 직접 쓴다.
local function int(x)
    return string.format('%d', x)
end

-- ARGV의 "" = 값 없음.
local function arg_or_nil(x)
    if x == nil or x == '' then return nil end
    return x
end

-- §6.2: Java domain/Geo.haversineKm과 같은 식·같은 반지름·같은 연산 순서.
local function haversine_km(lat1, lng1, lat2, lng2)
    local R = 6371.0
    local dLat = math.rad(lat2 - lat1)
    local dLng = math.rad(lng2 - lng1)
    local a = math.sin(dLat / 2) * math.sin(dLat / 2)
            + math.cos(math.rad(lat1)) * math.cos(math.rad(lat2))
            * math.sin(dLng / 2) * math.sin(dLng / 2)
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))
end

local function deal_key(dealId) return 'deal:' .. dealId end
local function bids_key(dealId) return 'deal:' .. dealId .. ':bids' end
local function last_bid_key(dealId) return 'deal:' .. dealId .. ':lastBid' end
local function driver_deals_key(driverId) return 'driver:' .. driverId .. ':deals' end
local function driver_state_key(driverId) return 'driver:' .. driverId .. ':state' end

-- 거래 Hash에서 숫자로 읽는 필드. 나머지는 문자열 그대로.
local NUMERIC_FIELDS = {
    originLat = true, originLng = true, basePrice = true, bandMin = true, bandMax = true,
    round = true, version = true, withdrawCount = true, nextBidSeq = true,
    createdAt = true, expiresAt = true, purgeAt = true,
    offerTtlMs = true, roundLimit = true, avgSpeedKmh = true, detourFactor = true, maxActiveBids = true,
    offerPrice = true, offerCreatedAt = true, offerExpiresAt = true, lastOfferPrice = true,
    closedAt = true, finalPrice = true, chosenRank = true, matchLowestBidPrice = true,
    winningPickupDistanceKm = true, winningPickupEtaMin = true,
    lowestBidPickupDistanceKm = true, lowestBidPickupEtaMin = true, matchedAt = true,
}

-- 그중 정수 필드 (get_deal이 JSON 숫자로 내보낸다).
local INTEGER_FIELDS = {
    round = true, version = true, withdrawCount = true, nextBidSeq = true,
    createdAt = true, expiresAt = true, purgeAt = true,
    offerTtlMs = true, roundLimit = true, maxActiveBids = true,
    offerCreatedAt = true, offerExpiresAt = true, closedAt = true, chosenRank = true, matchedAt = true,
}

-- Hash를 읽어 field 사전순 목록과 field→value 테이블로 돌려준다.
local function sorted_hash(key)
    local flat = redis.call('HGETALL', key)
    local fields, values = {}, {}
    for i = 1, #flat, 2 do
        fields[#fields + 1] = flat[i]
        values[flat[i]] = flat[i + 1]
    end
    table.sort(fields)
    return fields, values
end

-- 거래 Hash → 테이블(숫자 필드는 숫자). 없으면 nil.
local function load_deal(dealId)
    local fields, values = sorted_hash(deal_key(dealId))
    if #fields == 0 then return nil end
    local deal = {}
    for _, f in ipairs(fields) do
        if NUMERIC_FIELDS[f] then deal[f] = tonumber(values[f]) else deal[f] = values[f] end
    end
    return deal
end

local function is_active(deal)
    return deal.status == 'OPEN' or deal.status == 'NEGOTIATING'
end

-- 살아 있는 호가(:bids Hash)를 (price, seq) 오름차순으로. 원소는 저장된 호가 JSON을 디코드한 테이블.
local function ranked_bids(dealId)
    local fields, values = sorted_hash(bids_key(dealId))
    local bids = {}
    for _, driverId in ipairs(fields) do
        bids[#bids + 1] = cjson.decode(values[driverId])
    end
    table.sort(bids, function(a, b)
        local pa, pb = tonumber(a.price), tonumber(b.price)
        if pa ~= pb then return pa < pb end
        return a.seq < b.seq
    end)
    return bids
end

-- 최저 호가 가격(숫자), 호가가 없으면 nil.
local function lowest_price(dealId)
    local ranked = ranked_bids(dealId)
    if #ranked == 0 then return nil end
    return tonumber(ranked[1].price)
end

local function num_or_null(x)
    if x == nil then return cjson.null end
    return num(x)
end

-- R11 기사 ONLINE 판정 (§6.6): MATCHED면 불가, 아니면 presence 유효 또는 활성 호가 1건 이상.
local function driver_online(driverId, nowMs)
    if redis.call('HGET', driver_state_key(driverId), 'status') == 'MATCHED' then return false end
    local exp = redis.call('HGET', 'presence:driver:' .. driverId, 'expiresAt')
    if exp and tonumber(exp) > nowMs then return true end
    return redis.call('SCARD', driver_deals_key(driverId)) > 0
end

-- 이벤트 (필드 이름은 §5.3 그대로, 실수는 '%.17g' 문자열, 정수는 숫자).
local function ev_bid(name, dealId, bid, lowest, bidderCount, pendingSide, round, version)
    return { event = name, dealId = dealId, bid = bid, lowestBidPrice = num_or_null(lowest),
             bidderCount = bidderCount, pendingSide = pendingSide, round = round, version = version }
end

local function ev_bid_withdrawn(dealId, bidId, driverId, reason, lowest, bidderCount, round, version)
    return { event = 'bid.withdrawn', dealId = dealId, bidId = bidId, driverId = driverId, reason = reason,
             lowestBidPrice = num_or_null(lowest), bidderCount = bidderCount, round = round, version = version }
end

local function ev_offer_posted(dealId, price, expiresAt, pendingSide, round, version)
    return { event = 'offer.posted', dealId = dealId, price = num(price), expiresAt = expiresAt,
             pendingSide = pendingSide, round = round, version = version }
end

local function ev_offer_expired(dealId, pendingSide, round, version)
    return { event = 'offer.expired', dealId = dealId, pendingSide = pendingSide, round = round, version = version }
end

-- m: driverId, finalPrice, matchPath, chosenRank, lowestBidPrice, pickupDistanceKm, pickupEtaMin,
--    lowestBidPickupDistanceKm, lowestBidPickupEtaMin, matchedAt (없는 값은 nil)
local function ev_deal_matched(dealId, m, version)
    return { event = 'deal.matched', dealId = dealId, driverId = m.driverId, finalPrice = num(m.finalPrice),
             matchPath = m.matchPath, pickupDistanceKm = num_or_null(m.pickupDistanceKm),
             pickupEtaMin = num_or_null(m.pickupEtaMin), lowestBidPrice = num_or_null(m.lowestBidPrice),
             lowestBidPickupDistanceKm = num_or_null(m.lowestBidPickupDistanceKm),
             lowestBidPickupEtaMin = num_or_null(m.lowestBidPickupEtaMin),
             chosenRank = m.chosenRank, matchedAt = m.matchedAt, version = version }
end

local function ev_deal_expired(dealId, reason, version)
    return { event = 'deal.expired', dealId = dealId, reason = reason, version = version }
end

local function new_out()
    return { events = {}, closed = {}, requesterError = nil }
end

local function emit(out, event)
    out.events[#out.events + 1] = event
end

local function remove_offer(dealId)
    redis.call('HDEL', deal_key(dealId), 'offerPrice', 'offerCreatedAt', 'offerExpiresAt')
    redis.call('ZREM', 'offers:expiry', dealId)
end

-- 종료 정리 (§6.1 마지막 단락, 체결·만료·취소 공통). status/endReason/closedAt을 쓰고 version +1,
-- 오퍼 제거, 인덱스에서 빼고, 남은 호가를 낸 모든 기사의 driver:{id}:deals에서 이 거래를 뺀다.
-- 체결이 아니면 호가도 지우고 deal.expired(reason)를 낸다. 새 version을 돌려준다.
local function close_deal(deal, status, reason, nowMs, out)
    local dealId = deal.dealId
    local key = deal_key(dealId)
    redis.call('HSET', key, 'status', status, 'closedAt', int(nowMs))
    if reason then redis.call('HSET', key, 'endReason', reason) end
    local version = redis.call('HINCRBY', key, 'version', 1)
    remove_offer(dealId)
    redis.call('ZREM', 'deals:expiry', dealId)
    redis.call('ZREM', 'geo:deals', dealId)
    local drivers = redis.call('HKEYS', bids_key(dealId))
    table.sort(drivers)
    for _, driverId in ipairs(drivers) do
        redis.call('SREM', driver_deals_key(driverId), dealId)
    end
    if status ~= 'MATCHED' then
        redis.call('DEL', bids_key(dealId))
        emit(out, ev_deal_expired(dealId, reason, version))
    end
    deal.status = status
    deal.version = version
    out.closed[#out.closed + 1] = dealId
    out.closedAt = nowMs
    return version
end

-- R10: 승자의 다른 거래(dealId 사전순) 중 OPEN/NEGOTIATING이고(만료 시각은 보지 않음) 그 기사 호가가
-- 있는 것마다 호가 제거·version +1·bid.withdrawn(DRIVER_MATCHED_ELSEWHERE). withdrawCount는 그대로.
-- 마지막에 driver:{id}:deals를 지운다.
local function withdraw_elsewhere(driverId, keepDealId, nowMs, out)
    local setKey = driver_deals_key(driverId)
    local others = redis.call('SMEMBERS', setKey)
    table.sort(others)
    for _, otherId in ipairs(others) do
        if otherId ~= keepDealId then
            local other = load_deal(otherId)
            local raw = redis.call('HGET', bids_key(otherId), driverId)
            if other and is_active(other) and raw then
                local bid = cjson.decode(raw)
                redis.call('HDEL', bids_key(otherId), driverId)
                local version = redis.call('HINCRBY', deal_key(otherId), 'version', 1)
                emit(out, ev_bid_withdrawn(otherId, bid.bidId, driverId, 'DRIVER_MATCHED_ELSEWHERE',
                        lowest_price(otherId), redis.call('HLEN', bids_key(otherId)), other.round, version))
            end
        end
    end
    redis.call('DEL', setKey)
end

-- 체결 (§6.6): 체결 필드 기록 → 종료 정리(오퍼 제거, version +1) → deal.matched → R10.
local function match_deal(deal, m, nowMs, out)
    local key = deal_key(deal.dealId)
    redis.call('HSET', key, 'matchDriverId', m.driverId, 'finalPrice', num(m.finalPrice),
            'matchPath', m.matchPath, 'chosenRank', int(m.chosenRank), 'matchedAt', int(m.matchedAt))
    local optional = {
        { 'matchLowestBidPrice', m.lowestBidPrice },
        { 'winningPickupDistanceKm', m.pickupDistanceKm },
        { 'winningPickupEtaMin', m.pickupEtaMin },
        { 'lowestBidPickupDistanceKm', m.lowestBidPickupDistanceKm },
        { 'lowestBidPickupEtaMin', m.lowestBidPickupEtaMin },
    }
    for _, pair in ipairs(optional) do
        if pair[2] ~= nil then redis.call('HSET', key, pair[1], num(pair[2])) end
    end
    local version = close_deal(deal, 'MATCHED', nil, nowMs, out)
    emit(out, ev_deal_matched(deal.dealId, m, version))
    redis.call('HSET', driver_state_key(m.driverId), 'status', 'MATCHED', 'dealId', deal.dealId)
    redis.call('ZREM', 'geo:drivers', m.driverId)
    withdraw_elsewhere(m.driverId, deal.dealId, nowMs, out)
end

local function reply_ok(out)
    local r = { ok = true, events = out.events, closed = out.closed }
    if out.requesterError then r.requesterError = out.requesterError else r.requesterError = cjson.null end
    if out.closedAt then r.closedAt = out.closedAt else r.closedAt = cjson.null end
    return cjson.encode(r)
end

local function reply_err(code, message, version)
    return cjson.encode({ ok = false, code = code, message = message, version = version })
end

local function fmt1(x)
    return string.format('%.1f', x)
end

-- 명령 공통 검사 1~5 (§6.6). actorKind = 'RIDER' | 'DRIVER'. 통과하면 nil, 아니면 reply_err 문자열.
-- checkVersion = false면 5단계(version)를 건너뛴다(취소).
local function check_common(deal, nowMs, actorKind, actorId, version, checkVersion)
    if not deal then
        return reply_err('DEAL_NOT_ACTIVE', '거래가 없습니다', 0)
    end
    if deal.status == 'MATCHED' then
        return reply_err('DEAL_ALREADY_MATCHED', '이미 체결된 거래입니다', deal.version)
    end
    if not is_active(deal) then
        return reply_err('DEAL_NOT_ACTIVE', '종료된 거래입니다', deal.version)
    end
    if nowMs >= deal.expiresAt then
        return reply_err('DEAL_NOT_ACTIVE', '거래 시간이 만료되었습니다', deal.version)
    end
    if actorKind == 'RIDER' then
        if actorId == nil or actorId ~= deal.riderId then
            return reply_err('NOT_DEAL_OWNER', '본인의 거래가 아닙니다', deal.version)
        end
    else
        if actorId == nil or not driver_online(actorId, nowMs) then
            return reply_err('DRIVER_NOT_AVAILABLE', '지금은 호가·수락을 할 수 없는 기사입니다', deal.version)
        end
    end
    if checkVersion and version ~= nil and tonumber(version) ~= deal.version then
        return reply_err('VERSION_CONFLICT',
                '거래가 갱신되었습니다(현재 version ' .. int(deal.version) .. '). 다시 불러오세요', deal.version)
    end
    return nil
end

local function out_of_band(deal)
    return reply_err('OUT_OF_BAND',
            '허용 가격 범위(' .. fmt1(deal.bandMin) .. ' ~ ' .. fmt1(deal.bandMax) .. ')를 벗어났습니다', deal.version)
end

-- R8: 라운드 상한에 걸린 행위는 반영하지 않고 거래를 EXPIRED(ROUND_LIMIT)로 닫는다. 거부가 아니다.
local function round_limit(deal, nowMs, out)
    local version = close_deal(deal, 'EXPIRED', 'ROUND_LIMIT', nowMs, out)
    out.requesterError = { code = 'ROUND_LIMIT_EXCEEDED',
                           message = '라운드 상한(' .. int(deal.roundLimit) .. '회)을 넘어 거래가 종료되었습니다',
                           version = version }
    return reply_ok(out)
end

-- ===== 여기부터 각 스크립트 본문 =====
