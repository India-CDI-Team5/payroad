-- get_deal.lua: 읽기 전용 스냅샷 (api-spec §4.2). 아무 키도 바꾸지 않는다.
-- ARGV: nowMs, dealId
local dealId = ARGV[2]

local fields, values = sorted_hash(deal_key(dealId))
if #fields == 0 then
    return reply_err('DEAL_NOT_ACTIVE', '거래가 없습니다', 0)
end

local deal = {}
for _, f in ipairs(fields) do
    if INTEGER_FIELDS[f] then deal[f] = tonumber(values[f]) else deal[f] = values[f] end
end
deal.bids = ranked_bids(dealId)

local lastFields, lastValues = sorted_hash(last_bid_key(dealId))
local lastBid = {}
for _, driverId in ipairs(lastFields) do
    lastBid[driverId] = lastValues[driverId]
end
deal.lastBid = lastBid

return cjson.encode({ ok = true, deal = deal })
