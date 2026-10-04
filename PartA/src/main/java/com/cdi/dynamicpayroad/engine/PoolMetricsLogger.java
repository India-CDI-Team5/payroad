package com.cdi.dynamicpayroad.engine;

import com.cdi.dynamicpayroad.pool.OnlinePool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.stereotype.Component;

/**
 * Load-test instrumentation only: exposes the two custom thread pools'
 * saturation (active threads / queue depth) and how late scheduled call
 * attempts are actually firing, so pool sizing can be justified by numbers
 * instead of "seemed reasonable at the time".
 */
@Component
public class PoolMetricsLogger {
    private static final Logger log = LoggerFactory.getLogger(PoolMetricsLogger.class);

    private final SimulationEngine simulationEngine;
    private final ThreadPoolTaskExecutor matchResultExecutor;
    private final OnlinePool pool;

    public PoolMetricsLogger(SimulationEngine simulationEngine,
                              @Qualifier("matchResultExecutor") ThreadPoolTaskExecutor matchResultExecutor,
                              OnlinePool pool) {
        this.simulationEngine = simulationEngine;
        this.matchResultExecutor = matchResultExecutor;
        this.pool = pool;
    }

    @Scheduled(fixedRate = 5000)
    public void report() {
        int mrActive = matchResultExecutor.getActiveCount();
        int mrQueue = matchResultExecutor.getThreadPoolExecutor().getQueue().size();
        log.info("POOL-METRICS onlineUsers={} waitingDrivers={} | tripScheduler active={} queued={} | matchResultExecutor active={}/{} queued={}/500 | avgCallAttemptLagMs={}",
                pool.users().size(), pool.waitingDrivers().size(),
                simulationEngine.tripSchedulerActiveCount(), simulationEngine.tripSchedulerQueueSize(),
                mrActive, matchResultExecutor.getPoolSize(), mrQueue,
                String.format("%.1f", simulationEngine.drainAverageLagMs()));
    }
}
