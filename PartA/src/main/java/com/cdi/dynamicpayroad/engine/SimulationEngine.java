package com.cdi.dynamicpayroad.engine;

import com.cdi.dynamicpayroad.model.Driver;
import com.cdi.dynamicpayroad.model.MatchResult;
import com.cdi.dynamicpayroad.model.User;
import com.cdi.dynamicpayroad.pool.OnlinePool;
import com.cdi.dynamicpayroad.repository.DriverRepository;
import com.cdi.dynamicpayroad.repository.UserRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.List;
import java.util.Random;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Runs forever (no termination condition). The @Scheduled tick only drives
 * churn (online/offline flips) and stays on a fixed 1s cadence for that.
 * Call attempts are deliberately NOT tick-synchronized: real riders don't
 * all decide to request a ride on the same global clock edge. Instead, each
 * user schedules their own next attempt at an independent random delay
 * (scheduleNextCallAttempt), so attempts land at different real timestamps
 * and genuinely overlap across the tripScheduler's worker threads — the
 * same pool that already runs trip-completion callbacks. Each successful
 * match spins off its own one-shot "trip completion" task so the driver
 * returns to the waiting pool without blocking anything else.
 */
@Component
public class SimulationEngine {

    private static final Logger log = LoggerFactory.getLogger(SimulationEngine.class);

    private static final double USER_ONLINE_RATIO = 0.05;
    private static final double DRIVER_ONLINE_RATIO = 0.70;
    /** Base per-tick flip chance; scaled by the target ratio so each entity's
     *  own coin flip trends toward the ratio without ever being guaranteed. */
    private static final double CHURN_INTENSITY = 0.05;
    private static final double USER_ON_PROB = CHURN_INTENSITY * USER_ONLINE_RATIO;
    private static final double USER_OFF_PROB = CHURN_INTENSITY * (1 - USER_ONLINE_RATIO);
    private static final double DRIVER_ON_PROB = CHURN_INTENSITY * DRIVER_ONLINE_RATIO;
    private static final double DRIVER_OFF_PROB = CHURN_INTENSITY * (1 - DRIVER_ONLINE_RATIO);
    /** Each online user's next call attempt lands somewhere in this window,
     *  independent of every other user's — this is what makes attempts overlap
     *  instead of firing in lockstep on the tick. */
    private static final long MIN_CALL_DELAY_MS = 1000;
    private static final long MAX_CALL_DELAY_MS = 8000;
    private static final long MIN_TRIP_MS = 3000;
    private static final long MAX_TRIP_MS = 10000;

    /** Fare model (₹): flag-down + per-km, then multiplied by the surge weight. */
    private static final double FLAG_FARE = 30.0;
    private static final double PER_KM_FARE = 15.0;

    private final UserRepository userRepository;
    private final DriverRepository driverRepository;
    private final MatchResultRecorder matchResultRecorder;
    private final OnlinePool pool;
    private final MatchingEngine matching;
    private final Random rnd = new Random();
    private final ScheduledThreadPoolExecutor tripScheduler;

    /** Scheduling-lag accumulator: how much later than requested a call-attempt
     *  actually fired. Drained by PoolMetricsLogger; not meant to be read live. */
    private final AtomicLong lagSumMs = new AtomicLong();
    private final AtomicLong lagCount = new AtomicLong();

    public SimulationEngine(UserRepository userRepository, DriverRepository driverRepository,
                             MatchResultRecorder matchResultRecorder, OnlinePool pool,
                             MatchingEngine matching,
                             @org.springframework.beans.factory.annotation.Value("${simulation.trip-scheduler-pool-size:4}") int tripSchedulerPoolSize) {
        this.userRepository = userRepository;
        this.driverRepository = driverRepository;
        this.matchResultRecorder = matchResultRecorder;
        this.pool = pool;
        this.matching = matching;
        this.tripScheduler = (ScheduledThreadPoolExecutor) Executors.newScheduledThreadPool(tripSchedulerPoolSize);
    }

    @Scheduled(fixedRate = 1000)
    public void tick() {
        churnUsers();
        churnDrivers();
    }

    /**
     * Every offline user independently rolls a coin to come online; every
     * idle online user (still in the pool, i.e. not mid-match) independently
     * rolls a coin to go offline. No tick is guaranteed to flip anyone, and
     * none is guaranteed not to — only the long-run average tracks the 5%
     * target, via the coupled ON/OFF probabilities above. A user who just
     * came online immediately schedules their own first call attempt.
     */
    private void churnUsers() {
        List<User> newlyOnline = new java.util.ArrayList<>();
        for (User u : userRepository.findByStatus(User.Status.OFFLINE)) {
            if (rnd.nextDouble() < USER_ON_PROB) {
                u.setStatus(User.Status.ONLINE);
                userRepository.save(u);
                newlyOnline.add(u);
            }
        }
        pool.addUsersBulk(newlyOnline);
        newlyOnline.forEach(this::scheduleNextCallAttempt);

        for (User u : List.copyOf(pool.users())) {
            if (rnd.nextDouble() < USER_OFF_PROB && pool.removeUser(u.getId()) != null) {
                u.setStatus(User.Status.OFFLINE);
                userRepository.save(u);
            }
        }
    }

    /** Same independent coin-flip churn as users, but toward the 70% driver target. */
    private void churnDrivers() {
        List<Driver> newlyWaiting = new java.util.ArrayList<>();
        for (Driver d : driverRepository.findByStatus(Driver.Status.OFFLINE)) {
            if (rnd.nextDouble() < DRIVER_ON_PROB) {
                d.setStatus(Driver.Status.WAITING);
                driverRepository.save(d);
                newlyWaiting.add(d);
            }
        }
        pool.addWaitingDriversBulk(newlyWaiting);

        for (Driver d : List.copyOf(pool.waitingDrivers())) {
            if (rnd.nextDouble() < DRIVER_OFF_PROB && pool.claimDriver(d.getId()) != null) {
                d.setStatus(Driver.Status.OFFLINE);
                driverRepository.save(d);
            }
        }
    }

    /**
     * Schedules this user's next call attempt at an independent random delay.
     * Runs on tripScheduler (the same pool used for trip completions), so
     * many users' attempts genuinely execute concurrently on different
     * worker threads instead of all landing on one tick thread.
     */
    /** Public so SimulationBootstrap can kick off the initially-online users too
     *  (they're seeded straight into the pool without going through churnUsers()). */
    public void scheduleNextCallAttempt(User user) {
        long delayMs = MIN_CALL_DELAY_MS + rnd.nextLong(MAX_CALL_DELAY_MS - MIN_CALL_DELAY_MS);
        long scheduledFor = System.currentTimeMillis() + delayMs;
        tripScheduler.schedule(() -> {
            lagSumMs.addAndGet(Math.max(0, System.currentTimeMillis() - scheduledFor));
            lagCount.incrementAndGet();
            tryCallAttempt(user);
        }, delayMs, TimeUnit.MILLISECONDS);
    }

    /** For PoolMetricsLogger: active worker count on the trip/call-attempt pool. */
    public int tripSchedulerActiveCount() { return tripScheduler.getActiveCount(); }

    /** For PoolMetricsLogger: how many scheduled tasks are waiting for a free worker. */
    public int tripSchedulerQueueSize() { return tripScheduler.getQueue().size(); }

    /** For PoolMetricsLogger: average ms a call attempt fired late by, since the last drain. */
    public double drainAverageLagMs() {
        long count = lagCount.getAndSet(0);
        long sum = lagSumMs.getAndSet(0);
        return count == 0 ? 0.0 : (double) sum / count;
    }

    /**
     * Fires on a tripScheduler thread, possibly at the same instant as other
     * users' attempts or a churn flip on the tick thread. Re-checks presence
     * in the pool first since churn or a prior match may have removed this
     * user since the attempt was scheduled. A user who doesn't find a driver
     * this time keeps trying — their online session doesn't otherwise end
     * until churn takes them offline.
     */
    private void tryCallAttempt(User user) {
        if (!pool.isUserOnline(user.getId())) return;
        if (!attemptMatch(user)) {
            scheduleNextCallAttempt(user);
        }
    }

    /** @return true if this attempt found and claimed a driver. */
    private boolean attemptMatch(User user) {
        // process1: nearest driver + local demand/supply surge within 5km (Redis GEO-backed).
        MatchingEngine.Outcome outcome = matching.evaluate(user);
        if (!outcome.matched()) return false;

        Driver claimed = pool.claimDriver(outcome.driver().getId());
        if (claimed == null) return false;

        pool.removeUser(user.getId());

        claimed.setStatus(Driver.Status.DRIVING);
        driverRepository.save(claimed);

        double baseFare = FLAG_FARE + PER_KM_FARE * outcome.pickupDistanceKm();
        double finalFare = baseFare * outcome.surge();

        matchResultRecorder.record(new MatchResult(
                user.getId(), claimed.getId(), Instant.now(),
                outcome.pickupDistanceKm(), outcome.demandInRadius(), outcome.supplyInRadius(),
                outcome.surge(), baseFare, finalFare));
        log.info("MATCHED user={} driver={} dist={}km demand={} supply={} surge={}x fare={}",
                user.getId(), claimed.getId(),
                String.format("%.2f", outcome.pickupDistanceKm()),
                outcome.demandInRadius(), outcome.supplyInRadius(),
                outcome.surge(), String.format("%.1f", finalFare));

        long tripMs = MIN_TRIP_MS + rnd.nextInt((int) (MAX_TRIP_MS - MIN_TRIP_MS));
        tripScheduler.schedule(() -> completeTrip(user, claimed), tripMs, TimeUnit.MILLISECONDS);
        return true;
    }

    private void completeTrip(User user, Driver driver) {
        driver.setStatus(Driver.Status.WAITING);
        driverRepository.save(driver);
        pool.addWaitingDriver(driver);

        user.setStatus(User.Status.OFFLINE);
        userRepository.save(user);
        log.info("TRIP DONE driver={} -> waiting pool, user={} -> offline", driver.getId(), user.getId());
    }
}
