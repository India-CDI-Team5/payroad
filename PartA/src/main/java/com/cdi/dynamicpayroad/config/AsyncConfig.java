package com.cdi.dynamicpayroad.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.ThreadPoolExecutor;

/**
 * The 1-second tick (SimulationEngine) has a fixed budget: it must finish
 * churn + matching before the next @Scheduled invocation fires, or ticks
 * start piling up. MatchResult persistence is a DB write on that same
 * thread with no bearing on tick correctness (the online-pool state, not
 * this row, is the source of truth for "is this driver free"), so it's
 * moved off the tick thread onto this bounded pool instead of growing the
 * tick's own latency as match volume grows.
 */
@Configuration
@EnableAsync
public class AsyncConfig {
    private static final int CORE_POOL_SIZE = 4;
    private static final int MAX_POOL_SIZE = 16;
    private static final int QUEUE_CAPACITY = 500;

    @Bean(name = "matchResultExecutor")
    public ThreadPoolTaskExecutor matchResultExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(CORE_POOL_SIZE);
        executor.setMaxPoolSize(MAX_POOL_SIZE);
        executor.setQueueCapacity(QUEUE_CAPACITY);
        executor.setThreadNamePrefix("MatchPersist-");
        executor.initialize();
        return executor;
    }

    /**
     * A load test caught OnlinePool's GEOADD/ZREM calls blocking the single-
     * threaded @Scheduled tick for 149s under heavy churn — the exact same
     * "don't do I/O on a thread something else depends on" mistake as above,
     * just with Redis instead of the DB. Same fix, same shape of pool.
     */
    @Bean(name = "geoIndexExecutor")
    public ThreadPoolTaskExecutor geoIndexExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(CORE_POOL_SIZE);
        executor.setMaxPoolSize(MAX_POOL_SIZE);
        executor.setQueueCapacity(QUEUE_CAPACITY);
        executor.setThreadNamePrefix("GeoIndex-");
        // A burst (e.g. bootstrap activating thousands of users at once) can fill
        // this queue faster than it drains. Default AbortPolicy turned that into an
        // uncaught RejectedExecutionException that crashed the whole app context.
        // Since a missed index update is already documented as safe to lose
        // (GeoIndexWriter javadoc), discard instead of aborting.
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.DiscardPolicy());
        executor.initialize();
        return executor;
    }
}
