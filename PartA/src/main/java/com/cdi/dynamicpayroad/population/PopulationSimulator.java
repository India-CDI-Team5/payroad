package com.cdi.dynamicpayroad.population;

import com.cdi.dynamicpayroad.redis.RedisMarket;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Random;

/**
 * Keeps about 5% of the virtual users and 70% of the virtual drivers online (api-spec §6.7) through
 * the same presence scripts real clients use, so the supply/demand numbers (§4.8) look alive.
 * It only logs people on and off: no deals, bids or offers, nothing in DealHistory. No Spring here.
 */
public class PopulationSimulator {

    private static final Logger log = LoggerFactory.getLogger(PopulationSimulator.class);

    private static final Duration PRESENCE_TTL = Duration.ofSeconds(60);
    private static final int LOG_EVERY_STEPS = 60;

    /** One virtual person: fixed position, online flag, time of the last presence_upsert. */
    private static final class Person {
        final String type;
        final String id;
        final double lat;
        final double lng;
        boolean online;
        Instant lastBeat;

        Person(String type, String id, double lat, double lng) {
            this.type = type;
            this.id = id;
            this.lat = lat;
            this.lng = lng;
        }
    }

    private final PopulationProperties props;
    private final RedisMarket redisMarket;
    private final Clock clock;

    private Random rnd;
    /** Both in ID order, which is also creation order. */
    private List<Person> users = List.of();
    private List<Person> drivers = List.of();
    private long steps;

    public PopulationSimulator(PopulationProperties props, RedisMarket redisMarket, Clock clock) {
        this.props = props;
        this.redisMarket = redisMarket;
        this.clock = clock;
    }

    /** Creates the population and logs exactly userCount × ratio users and driverCount × ratio drivers on. */
    public synchronized void start() {
        rnd = new Random(props.getSeed());
        steps = 0;
        users = new ArrayList<>();
        drivers = new ArrayList<>();
        for (int i = 0; i < props.getUserCount(); i++) {
            users.add(randomPerson("RIDER", String.format("SIM-U%04d", i)));
        }
        for (int i = 0; i < props.getDriverCount(); i++) {
            drivers.add(randomPerson("DRIVER", String.format("SIM-D%03d", i)));
        }

        Instant now = clock.instant();
        activateInitial(users, props.getUserOnlineRatio(), now);
        activateInitial(drivers, props.getDriverOnlineRatio(), now);
    }

    /** One second: users then drivers flip their coins, then the online ones heartbeat when due. */
    public synchronized void step() {
        if (rnd == null) return;   // the scheduler can fire before start()
        Instant now = clock.instant();
        churn(users, props.getUserOnlineRatio(), now);
        churn(drivers, props.getDriverOnlineRatio(), now);
        heartbeat(users, now);
        heartbeat(drivers, now);

        steps++;
        if (steps % LOG_EVERY_STEPS == 0) {
            log.info("POPULATION users={}/{} drivers={}/{}",
                    onlineUsers(), users.size(), onlineDrivers(), drivers.size());
        }
    }

    public synchronized int onlineUsers() {
        return countOnline(users);
    }

    public synchronized int onlineDrivers() {
        return countOnline(drivers);
    }

    private Person randomPerson(String type, String id) {
        double lat = props.getCenterLat() + (rnd.nextDouble() * 2 - 1) * props.getSpreadDeg();
        double lng = props.getCenterLng() + (rnd.nextDouble() * 2 - 1) * props.getSpreadDeg();
        return new Person(type, id, lat, lng);
    }

    /**
     * Shuffles a copy and logs the first (int)(n × ratio) on. Everyone else is logged off, so a
     * restart does not leave the previous run's people in Redis until their TTL runs out.
     */
    private void activateInitial(List<Person> people, double ratio, Instant now) {
        List<Person> shuffled = new ArrayList<>(people);
        Collections.shuffle(shuffled, rnd);
        int target = (int) (people.size() * ratio);
        for (int i = 0; i < shuffled.size(); i++) {
            Person p = shuffled.get(i);
            if (i < target) {
                goOnline(p, now);
            } else {
                p.online = false;
                redisMarket.removePresence(p.type, p.id, now);
            }
        }
    }

    /**
     * The old SimulationEngine coin flips: offline people come on with churn × ratio, online people
     * go off with churn × (1 − ratio), so the long-run share tends to the ratio.
     */
    private void churn(List<Person> people, double ratio, Instant now) {
        double onProb = props.getChurnIntensity() * ratio;
        double offProb = props.getChurnIntensity() * (1 - ratio);
        List<Person> offline = people.stream().filter(p -> !p.online).toList();
        List<Person> online = people.stream().filter(p -> p.online).toList();
        for (Person p : offline) {
            if (rnd.nextDouble() < onProb) goOnline(p, now);
        }
        for (Person p : online) {
            if (rnd.nextDouble() < offProb && redisMarket.removePresence(p.type, p.id, now)) {
                p.online = false;
            }
        }
    }

    private void heartbeat(List<Person> people, Instant now) {
        Duration every = Duration.ofSeconds(props.getHeartbeatSec());
        for (Person p : people) {
            if (p.online && !now.isBefore(p.lastBeat.plus(every))) {
                upsert(p, now);
            }
        }
    }

    private void goOnline(Person p, Instant now) {
        p.online = true;
        upsert(p, now);
    }

    private void upsert(Person p, Instant now) {
        redisMarket.upsertPresence(p.type, p.id, p.lat, p.lng, PRESENCE_TTL, now);
        p.lastBeat = now;
    }

    private static int countOnline(List<Person> people) {
        int n = 0;
        for (Person p : people) if (p.online) n++;
        return n;
    }
}
