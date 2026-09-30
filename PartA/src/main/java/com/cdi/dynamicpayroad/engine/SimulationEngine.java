package com.cdi.dynamicpayroad.engine;

import com.cdi.dynamicpayroad.model.Driver;
import com.cdi.dynamicpayroad.model.DealHistory;
import com.cdi.dynamicpayroad.model.User;
import com.cdi.dynamicpayroad.pool.OnlinePool;
import com.cdi.dynamicpayroad.repository.DriverRepository;
import com.cdi.dynamicpayroad.repository.DealHistoryRepository;
import com.cdi.dynamicpayroad.repository.UserRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.List;
import java.util.Random;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * Runs forever (no termination condition). The @Scheduled tick drives call
 * attempts + pool replenishment; each successful match spins off its own
 * one-shot "trip completion" task so the driver returns to the waiting pool
 * without blocking the next tick.
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
    private static final double CALL_ATTEMPT_PROBABILITY = 0.15;
    private static final long MIN_TRIP_MS = 3000;
    private static final long MAX_TRIP_MS = 10000;

    /** Fare model (₹): flag-down + per-km, then multiplied by the surge weight. */
    private static final double FLAG_FARE = 30.0;
    private static final double PER_KM_FARE = 15.0;

    private final UserRepository userRepository;
    private final DriverRepository driverRepository;
    private final DealHistoryRepository dealHistoryRepository;
    private final OnlinePool pool;
    private final MatchingEngine matching;
    private final Random rnd;
    private final long randomSeed;
    private final String experimentTag;
    private final ScheduledExecutorService tripScheduler = Executors.newScheduledThreadPool(4);

    public SimulationEngine(UserRepository userRepository, DriverRepository driverRepository,
                             DealHistoryRepository dealHistoryRepository, OnlinePool pool,
                             MatchingEngine matching,
                             @Value("${simulation.experiment-tag:baseline-surge}") String experimentTag,
                             @Value("${simulation.random-seed:#{null}}") Long randomSeed) {
        this.userRepository = userRepository;
        this.driverRepository = driverRepository;
        this.dealHistoryRepository = dealHistoryRepository;
        this.pool = pool;
        this.matching = matching;
        this.experimentTag = experimentTag;
        // No seed configured -> pick one, but still record it so the run can be replayed.
        this.randomSeed = randomSeed != null ? randomSeed : System.nanoTime();
        this.rnd = new Random(this.randomSeed);
    }

    @Scheduled(fixedRate = 1000)
    public void tick() {
        churnUsers();
        churnDrivers();
        requestCalls();
    }

    /**
     * Every offline user independently rolls a coin to come online; every
     * idle online user (still in the pool, i.e. not mid-match) independently
     * rolls a coin to go offline. No tick is guaranteed to flip anyone, and
     * none is guaranteed not to — only the long-run average tracks the 5%
     * target, via the coupled ON/OFF probabilities above.
     */
    private void churnUsers() {
        for (User u : userRepository.findByStatus(User.Status.OFFLINE)) {
            if (rnd.nextDouble() < USER_ON_PROB) {
                u.setStatus(User.Status.ONLINE);
                userRepository.save(u);
                pool.addUser(u);
            }
        }
        for (User u : List.copyOf(pool.users())) {
            if (rnd.nextDouble() < USER_OFF_PROB && pool.removeUser(u.getId()) != null) {
                u.setStatus(User.Status.OFFLINE);
                userRepository.save(u);
            }
        }
    }

    /** Same independent coin-flip churn as users, but toward the 70% driver target. */
    private void churnDrivers() {
        for (Driver d : driverRepository.findByStatus(Driver.Status.OFFLINE)) {
            if (rnd.nextDouble() < DRIVER_ON_PROB) {
                d.setStatus(Driver.Status.WAITING);
                driverRepository.save(d);
                pool.addWaitingDriver(d);
            }
        }
        for (Driver d : List.copyOf(pool.waitingDrivers())) {
            if (rnd.nextDouble() < DRIVER_OFF_PROB && pool.claimDriver(d.getId()) != null) {
                d.setStatus(Driver.Status.OFFLINE);
                driverRepository.save(d);
            }
        }
    }

    /** Only a random fraction of online users actually request a ride this tick. */
    private void requestCalls() {
        for (User user : List.copyOf(pool.users())) {
            if (rnd.nextDouble() < CALL_ATTEMPT_PROBABILITY) {
                attemptMatch(user);
            }
        }
    }

    private void attemptMatch(User user) {
        // process1: nearest driver + local demand/supply surge within 5km.
        MatchingEngine.Outcome outcome = matching.evaluate(user, pool.users(), pool.waitingDrivers());
        if (!outcome.matched()) return;

        Driver claimed = pool.claimDriver(outcome.driver().getId());
        if (claimed == null) return;

        pool.removeUser(user.getId());

        claimed.setStatus(Driver.Status.DRIVING);
        driverRepository.save(claimed);

        double basePrice = FLAG_FARE + PER_KM_FARE * outcome.pickupDistanceKm();
        double finalPrice = basePrice * outcome.surge();
        double markupRatio = finalPrice / basePrice;

        // No bargaining in this simulation yet: zero rounds, zero bidders, instant close.
        dealHistoryRepository.save(new DealHistory(
                user.getId(), claimed.getId(), Instant.now(),
                outcome.pickupDistanceKm(), outcome.demandInRadius(), outcome.supplyInRadius(),
                basePrice, finalPrice, markupRatio,
                0, 0, 0L,
                experimentTag, randomSeed));
        log.info("MATCHED user={} driver={} dist={}km demand={} supply={} surge={}x fare={}",
                user.getId(), claimed.getId(),
                String.format("%.2f", outcome.pickupDistanceKm()),
                outcome.demandInRadius(), outcome.supplyInRadius(),
                outcome.surge(), String.format("%.1f", finalPrice));

        long tripMs = MIN_TRIP_MS + rnd.nextInt((int) (MAX_TRIP_MS - MIN_TRIP_MS));
        tripScheduler.schedule(() -> completeTrip(user, claimed), tripMs, TimeUnit.MILLISECONDS);
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
