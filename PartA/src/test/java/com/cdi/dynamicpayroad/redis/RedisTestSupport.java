package com.cdi.dynamicpayroad.redis;

import com.cdi.dynamicpayroad.domain.DealRules;
import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisURI;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.sync.RedisCommands;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;

import static org.assertj.core.api.Assertions.fail;

/**
 * Real Redis for rule tests (api-spec §8: DB 15). The URL comes from the Gradle test task
 * (payroad.test.redis-url). A missing Redis fails the test instead of skipping it.
 * Every test starts from an empty DB.
 */
public abstract class RedisTestSupport {

    static final String NO_REDIS = "Redis 없음: 저장소 루트에서 docker compose up -d redis";

    protected static RedisClient client;
    protected static StatefulRedisConnection<String, String> connection;
    protected static RedisCommands<String, String> cmd;
    protected static int db;

    protected RedisMarket market;

    @BeforeAll
    static void connect() {
        RedisURI uri = RedisURI.create(System.getProperty("payroad.test.redis-url", "redis://localhost:6379/15"));
        if (uri.getDatabase() == 0) fail("테스트는 DB 0(실서비스)을 쓰지 않는다: " + uri);
        db = uri.getDatabase();
        client = RedisClient.create(uri);
        try {
            connection = client.connect();
        } catch (RuntimeException e) {
            client.shutdown();
            fail(NO_REDIS, e);
        }
        cmd = connection.sync();
    }

    @AfterAll
    static void disconnect() {
        if (connection != null) connection.close();
        if (client != null) client.shutdown();
    }

    @BeforeEach
    void flush() {
        market = new RedisMarket(cmd, db, rules());
        market.flushDb();
    }

    /** Override to run a test class with other rule values. */
    protected DealRules rules() {
        return DealRules.defaults();
    }
}
