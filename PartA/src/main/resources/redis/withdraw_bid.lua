-- withdraw_bid.lua: 기사 호가 철회 (R5, R11). 라운드에 들어가지 않고(R8), lastBid는 남는다(R1).
-- ARGV: nowMs, dealId, driverId, version
local nowMs = tonumber(ARGV[1])
local dealId = ARGV[2]
local driverId = arg_or_nil(ARGV[3])
local version = arg_or_nil(ARGV[4])

local deal = load_deal(dealId)
local refused = check_common(deal, nowMs, 'DRIVER', driverId, version, true)
if refused then return refused end

local raw = redis.call('HGET', bids_key(dealId), driverId)
if not raw then
    return reply_err('BID_NOT_FOUND', '철회할 호가가 없습니다', deal.version)
end
local bid = cjson.decode(raw)

local out = new_out()
redis.call('HDEL', bids_key(dealId), driverId)
redis.call('HINCRBY', deal_key(dealId), 'withdrawCount', 1)
local newVersion = redis.call('HINCRBY', deal_key(dealId), 'version', 1)
redis.call('SREM', driver_deals_key(driverId), dealId)

emit(out, ev_bid_withdrawn(dealId, bid.bidId, driverId, 'BY_DRIVER', lowest_price(dealId),
        redis.call('HLEN', bids_key(dealId)), deal.round, newVersion))
return reply_ok(out)
