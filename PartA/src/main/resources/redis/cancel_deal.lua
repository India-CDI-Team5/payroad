-- cancel_deal.lua: 승객 취소 (R12). version은 검사하지 않는다(§4.3).
-- ARGV: nowMs, dealId, riderId
local nowMs = tonumber(ARGV[1])
local dealId = ARGV[2]
local riderId = arg_or_nil(ARGV[3])

local deal = load_deal(dealId)
local refused = check_common(deal, nowMs, 'RIDER', riderId, nil, false)
if refused then return refused end

local out = new_out()
close_deal(deal, 'CANCELLED', 'CANCELLED_BY_RIDER', nowMs, out)
return reply_ok(out)
