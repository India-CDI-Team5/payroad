package com.cdi.dynamicpayroad.population;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** The virtual population (api-spec §6.7). Demo only: never used by the experiments or the paper. */
@ConfigurationProperties(prefix = "population")
public class PopulationProperties {

    private boolean enabled = true;
    private int userCount = 1000;
    private int driverCount = 200;
    private double userOnlineRatio = 0.05;
    private double driverOnlineRatio = 0.70;
    /** Base per-step flip chance, scaled by the target ratio (the old SimulationEngine.CHURN_INTENSITY). */
    private double churnIntensity = 0.05;
    private double centerLat = 12.9716;
    private double centerLng = 77.5946;
    private double spreadDeg = 0.1;
    private long seed = 42;
    private long heartbeatSec = 20;

    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean enabled) { this.enabled = enabled; }
    public int getUserCount() { return userCount; }
    public void setUserCount(int userCount) { this.userCount = userCount; }
    public int getDriverCount() { return driverCount; }
    public void setDriverCount(int driverCount) { this.driverCount = driverCount; }
    public double getUserOnlineRatio() { return userOnlineRatio; }
    public void setUserOnlineRatio(double userOnlineRatio) { this.userOnlineRatio = userOnlineRatio; }
    public double getDriverOnlineRatio() { return driverOnlineRatio; }
    public void setDriverOnlineRatio(double driverOnlineRatio) { this.driverOnlineRatio = driverOnlineRatio; }
    public double getChurnIntensity() { return churnIntensity; }
    public void setChurnIntensity(double churnIntensity) { this.churnIntensity = churnIntensity; }
    public double getCenterLat() { return centerLat; }
    public void setCenterLat(double centerLat) { this.centerLat = centerLat; }
    public double getCenterLng() { return centerLng; }
    public void setCenterLng(double centerLng) { this.centerLng = centerLng; }
    public double getSpreadDeg() { return spreadDeg; }
    public void setSpreadDeg(double spreadDeg) { this.spreadDeg = spreadDeg; }
    public long getSeed() { return seed; }
    public void setSeed(long seed) { this.seed = seed; }
    public long getHeartbeatSec() { return heartbeatSec; }
    public void setHeartbeatSec(long heartbeatSec) { this.heartbeatSec = heartbeatSec; }
}
