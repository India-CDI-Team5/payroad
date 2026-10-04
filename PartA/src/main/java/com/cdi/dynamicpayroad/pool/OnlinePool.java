package com.cdi.dynamicpayroad.pool;

import com.cdi.dynamicpayroad.model.Driver;
import com.cdi.dynamicpayroad.model.User;
import org.springframework.stereotype.Component;

import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * In-memory mirror of "currently online" entities. The ConcurrentHashMaps are
 * the source of truth for object lookup by id and for claimDriver's atomic
 * double-booking guard, updated synchronously and instantly. GeoIndexWriter
 * mirrors the same add/remove into Redis GEO asynchronously (see its javadoc
 * for why this must not be synchronous — a load test caught it blocking the
 * tick thread for 149s).
 */
@Component
public class OnlinePool {
    private final Map<String, User> onlineUsers = new ConcurrentHashMap<>();
    private final Map<String, Driver> waitingDrivers = new ConcurrentHashMap<>();
    private final GeoIndexWriter geoIndexWriter;

    public OnlinePool(GeoIndexWriter geoIndexWriter) {
        this.geoIndexWriter = geoIndexWriter;
    }

    public void addUser(User user) {
        onlineUsers.put(user.getId(), user);
        geoIndexWriter.addUser(user.getId(), user.getLocation().getLon(), user.getLocation().getLat());
    }

    public void addWaitingDriver(Driver driver) {
        waitingDrivers.put(driver.getId(), driver);
        geoIndexWriter.addDriver(driver.getId(), driver.getLocation().getLon(), driver.getLocation().getLat());
    }

    /** For bursts: churn onboarding a batch of users in one tick, or bootstrap
     *  activating the initial pool. One pipelined Redis round trip for the
     *  whole batch instead of one per user. */
    public void addUsersBulk(List<User> users) {
        if (users.isEmpty()) return;
        for (User u : users) onlineUsers.put(u.getId(), u);
        geoIndexWriter.addUsersBulk(users.stream()
                .map(u -> new GeoIndexWriter.GeoAdd(u.getId(), u.getLocation().getLon(), u.getLocation().getLat()))
                .toList());
    }

    public void addWaitingDriversBulk(List<Driver> drivers) {
        if (drivers.isEmpty()) return;
        for (Driver d : drivers) waitingDrivers.put(d.getId(), d);
        geoIndexWriter.addDriversBulk(drivers.stream()
                .map(d -> new GeoIndexWriter.GeoAdd(d.getId(), d.getLocation().getLon(), d.getLocation().getLat()))
                .toList());
    }

    public User removeUser(String id) {
        User removed = onlineUsers.remove(id);
        if (removed != null) {
            geoIndexWriter.removeUser(id, removed.getLocation().getLon(), removed.getLocation().getLat());
        }
        return removed;
    }

    public Driver claimDriver(String id) {
        Driver claimed = waitingDrivers.remove(id);
        if (claimed != null) {
            geoIndexWriter.removeDriver(id, claimed.getLocation().getLon(), claimed.getLocation().getLat());
        }
        return claimed;
    }

    public Collection<User> users() { return onlineUsers.values(); }
    public Collection<Driver> waitingDrivers() { return waitingDrivers.values(); }

    /** Non-removing lookup so MatchingEngine can resolve a GEO search hit (an id) back to the object. */
    public Driver peekWaitingDriver(String id) { return waitingDrivers.get(id); }

    /** Used by a scheduled call-attempt callback to check it hasn't been overtaken
     *  by churn (gone offline) or a match (already removed) since it was scheduled. */
    public boolean isUserOnline(String id) { return onlineUsers.containsKey(id); }
}
