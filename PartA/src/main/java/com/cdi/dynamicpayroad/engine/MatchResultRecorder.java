package com.cdi.dynamicpayroad.engine;

import com.cdi.dynamicpayroad.model.MatchResult;
import com.cdi.dynamicpayroad.repository.MatchResultRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;

/**
 * Persists MatchResult off the SimulationEngine tick thread (see AsyncConfig).
 * By the time this runs, the online-pool claim/remove for this match has
 * already happened synchronously in the tick, so a delayed insert here only
 * delays when the audit row becomes visible in match_result — it cannot
 * cause a double-booking or any other correctness issue in the pool.
 */
@Component
public class MatchResultRecorder {
    private static final Logger log = LoggerFactory.getLogger(MatchResultRecorder.class);

    private final MatchResultRepository matchResultRepository;

    public MatchResultRecorder(MatchResultRepository matchResultRepository) {
        this.matchResultRepository = matchResultRepository;
    }

    @Async("matchResultExecutor")
    public void record(MatchResult result) {
        try {
            matchResultRepository.save(result);
        } catch (Exception e) {
            log.error("MatchResult 저장 실패: userId={} driverId={}", result.getUserId(), result.getDriverId(), e);
        }
    }
}
