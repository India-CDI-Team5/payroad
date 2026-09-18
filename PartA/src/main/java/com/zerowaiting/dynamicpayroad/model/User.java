package com.zerowaiting.dynamicpayroad.model;

import jakarta.persistence.Embedded;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "app_user")
public class User {
    public enum Status { OFFLINE, ONLINE }

    @Id
    private String id;

    @Enumerated(EnumType.STRING)
    private Status status = Status.OFFLINE;

    @Embedded
    private Location location;

    protected User() {}

    public User(String id, Location location) {
        this.id = id;
        this.location = location;
    }

    public String getId() { return id; }
    public Status getStatus() { return status; }
    public void setStatus(Status status) { this.status = status; }
    public Location getLocation() { return location; }
}
