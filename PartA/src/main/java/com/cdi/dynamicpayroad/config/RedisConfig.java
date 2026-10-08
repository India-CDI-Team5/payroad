package com.cdi.dynamicpayroad.config;

import com.cdi.dynamicpayroad.domain.DealRules;
import com.cdi.dynamicpayroad.redis.RedisMarket;
import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisURI;
import io.lettuce.core.api.StatefulRedisConnection;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * One Lettuce connection to the Redis that holds every deal (api-spec §6.1: DB 0 live, 14 runner,
 * 15 JUnit — the number comes from the URL path), and the RedisMarket gateway on top of it.
 */
@Configuration
public class RedisConfig {

    @Bean
    public RedisURI redisUri(@Value("${spring.data.redis.url}") String url) {
        return RedisURI.create(url);
    }

    @Bean(destroyMethod = "shutdown")
    public RedisClient redisClient(RedisURI redisUri) {
        return RedisClient.create(redisUri);
    }

    @Bean(destroyMethod = "close")
    public StatefulRedisConnection<String, String> redisConnection(RedisClient redisClient) {
        return redisClient.connect();
    }

    @Bean
    public RedisMarket redisMarket(StatefulRedisConnection<String, String> redisConnection, RedisURI redisUri) {
        return new RedisMarket(redisConnection.sync(), redisUri.getDatabase(), DealRules.defaults());
    }
}
