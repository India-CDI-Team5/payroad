package com.cdi.dynamicpayroad.bootstrap;

import com.cdi.dynamicpayroad.model.Driver;
import com.cdi.dynamicpayroad.model.Location;
import com.cdi.dynamicpayroad.model.User;
import com.cdi.dynamicpayroad.pool.OnlinePool;
import com.cdi.dynamicpayroad.repository.DriverRepository;
import com.cdi.dynamicpayroad.repository.UserRepository;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Random;

/**
 * Seeds the DB on first run, then every startup resets everyone to
 * OFFLINE/OFFLINE and re-activates a fresh 5% user / 70% driver sample into
 * the in-memory pool, mirroring the persisted status back to the DB.
 */
@Component
public class SimulationBootstrap implements ApplicationRunner {

    private static final int USER_COUNT = 1000;
    private static final int DRIVER_COUNT = 200;
    private static final double USER_ONLINE_RATIO = 0.05;
    private static final double DRIVER_ONLINE_RATIO = 0.70;

    // City centre (Bengaluru) + spread. ±0.1° ≈ a ~22km box, so the 5km
    // matching radius captures a local neighbourhood, not the whole city.
    private static final double CENTER_LAT = 12.9716;
    private static final double CENTER_LON = 77.5946;
    private static final double SPREAD_DEG = 0.1;

    private final UserRepository userRepository;
    private final DriverRepository driverRepository;
    private final OnlinePool pool;
    private final Random rnd = new Random();

    public SimulationBootstrap(UserRepository userRepository, DriverRepository driverRepository, OnlinePool pool) {
        this.userRepository = userRepository;
        this.driverRepository = driverRepository;
        this.pool = pool;
    }

    @Override
    public void run(ApplicationArguments args) {
        seedIfEmpty();
        activateInitialPool();
    }

    private void seedIfEmpty() {
        if (userRepository.count() == 0) {
            List<User> users = new ArrayList<>();
            for (int i = 0; i < USER_COUNT; i++) {
                users.add(new User("U" + i, randomLocation()));
            }
            userRepository.saveAll(users);
        }
        if (driverRepository.count() == 0) {
            List<Driver> drivers = new ArrayList<>();
            for (int i = 0; i < DRIVER_COUNT; i++) {
                drivers.add(new Driver("D" + i, randomLocation()));
            }
            driverRepository.saveAll(drivers);
        }
    }

    private void activateInitialPool() {
        List<User> allUsers = userRepository.findAll();
        allUsers.forEach(u -> u.setStatus(User.Status.OFFLINE));
        Collections.shuffle(allUsers, rnd);
        int userTarget = (int) (allUsers.size() * USER_ONLINE_RATIO);
        allUsers.subList(0, Math.min(userTarget, allUsers.size()))
                .forEach(u -> u.setStatus(User.Status.ONLINE));
        userRepository.saveAll(allUsers);
        allUsers.stream()
                .filter(u -> u.getStatus() == User.Status.ONLINE)
                .forEach(pool::addUser);

        List<Driver> allDrivers = driverRepository.findAll();
        allDrivers.forEach(d -> d.setStatus(Driver.Status.OFFLINE));
        Collections.shuffle(allDrivers, rnd);
        int driverTarget = (int) (allDrivers.size() * DRIVER_ONLINE_RATIO);
        allDrivers.subList(0, Math.min(driverTarget, allDrivers.size()))
                .forEach(d -> d.setStatus(Driver.Status.WAITING));
        driverRepository.saveAll(allDrivers);
        allDrivers.stream()
                .filter(d -> d.getStatus() == Driver.Status.WAITING)
                .forEach(pool::addWaitingDriver);
    }

    private Location randomLocation() {
        double lat = CENTER_LAT + (rnd.nextDouble() * 2 - 1) * SPREAD_DEG;
        double lon = CENTER_LON + (rnd.nextDouble() * 2 - 1) * SPREAD_DEG;
        return new Location(lat, lon);
    }
}
