package com.zerowaiting.dynamicpayroad.pool;

import com.zerowaiting.dynamicpayroad.model.Driver;
import com.zerowaiting.dynamicpayroad.model.User;
import org.springframework.stereotype.Component;

import java.util.Collection;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * In-memory mirror of "currently online" entities. This is the only shared
 * state touched by both the tick loop and the trip-completion callbacks, so
 * every mutation goes through ConcurrentHashMap's atomic operations
 * (claimDriver = atomic remove) to avoid double-booking a driver.
 */
@Component
public class OnlinePool {
    private final Map<String, User> onlineUsers = new ConcurrentHashMap<>();
    private final Map<String, Driver> waitingDrivers = new ConcurrentHashMap<>();

    public void addUser(User user) { onlineUsers.put(user.getId(), user); }
    public void addWaitingDriver(Driver driver) { waitingDrivers.put(driver.getId(), driver); }

    public User removeUser(String id) { return onlineUsers.remove(id); }
    public Driver claimDriver(String id) { return waitingDrivers.remove(id); }

    public Collection<User> users() { return onlineUsers.values(); }
    public Collection<Driver> waitingDrivers() { return waitingDrivers.values(); }
}
