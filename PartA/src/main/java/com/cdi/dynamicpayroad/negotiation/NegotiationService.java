package com.cdi.dynamicpayroad.negotiation;

import org.springframework.core.io.ClassPathResource;
import org.springframework.data.redis.RedisSystemException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.scripting.support.ResourceScriptSource;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Minimal real implementation of the negotiation flow in docs/api-spec.md
 * (R1/R9/R10/R13 only — no TTL sweeper, no WebSocket broadcast, no price
 * band/R2). Deal/bid state lives entirely in Redis under the "nego:" prefix;
 * place_bid.lua and accept_bid.lua carry the actual correctness guarantees —
 * this class just loads them and shapes the Java-side calls.
 */
@Service
public class NegotiationService {

    private static final int MAX_ACTIVE_BIDS = 50;

    private final StringRedisTemplate redis;
    private final RedisScript<List> placeBidScript;
    private final RedisScript<List> acceptBidScript;

    public NegotiationService(StringRedisTemplate redis) {
        this.redis = redis;
        this.placeBidScript = loadScript("redis/place_bid.lua");
        this.acceptBidScript = loadScript("redis/accept_bid.lua");
    }

    private static RedisScript<List> loadScript(String classpathLocation) {
        DefaultRedisScript<List> script = new DefaultRedisScript<>();
        script.setScriptSource(new ResourceScriptSource(new ClassPathResource(classpathLocation)));
        script.setResultType(List.class);
        return script;
    }

    public String createDeal(String riderId, double basePrice) {
        String dealId = "D-" + UUID.randomUUID().toString().substring(0, 8);
        String key = dealKey(dealId);
        redis.opsForHash().putAll(key, Map.of(
                "status", "OPEN",
                "riderId", riderId,
                "basePrice", String.valueOf(basePrice),
                "version", "0"
        ));
        return dealId;
    }

    /** @return the new version on success. Throws NegotiationException(code) on rejection. */
    public long placeBid(String dealId, String driverId, double price) {
        List<Object> result = execute(placeBidScript,
                List.of(dealKey(dealId), bidsKey(dealId), bidsByPriceKey(dealId), lastBidKey(dealId), driverDealsKey(driverId)),
                driverId, String.valueOf(price), dealId, String.valueOf(MAX_ACTIVE_BIDS));
        return Long.parseLong((String) result.get(1));
    }

    /** @return the new version on success. Throws NegotiationException(code) on rejection. */
    public long acceptBid(String dealId, String driverId) {
        List<Object> result = execute(acceptBidScript,
                List.of(dealKey(dealId), driverDealsKey(driverId)),
                driverId, dealId);
        return Long.parseLong((String) result.get(1));
    }

    public Map<Object, Object> getDeal(String dealId) {
        return redis.opsForHash().entries(dealKey(dealId));
    }

    @SuppressWarnings("unchecked")
    private List<Object> execute(RedisScript<List> script, List<String> keys, Object... args) {
        try {
            return redis.execute(script, keys, args);
        } catch (RedisSystemException e) {
            String message = e.getRootCause() != null ? e.getRootCause().getMessage() : e.getMessage();
            throw new NegotiationException(extractErrorCode(message));
        }
    }

    /** Lettuce wraps the raw Lua error_reply string; pull just our error code out of it. */
    private static String extractErrorCode(String rawMessage) {
        if (rawMessage == null) return "UNKNOWN_ERROR";
        String[] parts = rawMessage.split("\\s+");
        return parts[parts.length - 1].replace(")", "").trim();
    }

    private static String dealKey(String dealId) { return "nego:deal:" + dealId; }
    private static String bidsKey(String dealId) { return "nego:deal:" + dealId + ":bids"; }
    private static String bidsByPriceKey(String dealId) { return "nego:deal:" + dealId + ":bidsByPrice"; }
    private static String lastBidKey(String dealId) { return "nego:deal:" + dealId + ":lastBid"; }
    private static String driverDealsKey(String driverId) { return "nego:driver:" + driverId + ":deals"; }
}
