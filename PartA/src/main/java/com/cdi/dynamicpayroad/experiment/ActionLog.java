package com.cdi.dynamicpayroad.experiment;

import com.cdi.dynamicpayroad.experiment.Agent.ActorType;

import java.util.ArrayList;
import java.util.List;

/**
 * Behaviour log for collusion detection (ml-design v5 §7.1): one row per command, presence
 * registration, and offer seen by a driver. Kept in memory; {@link CsvExporter} writes and clears it.
 */
public final class ActionLog {

    public enum Action { PRESENT, BID_PLACE, BID_UPDATE, WITHDRAW, ACCEPT_OFFER, OFFER_SEEN, OFFER_POST, ACCEPT_BID, CANCEL }

    /**
     * @param tSec       seconds since the deal was created
     * @param driverId   the driver's id for a driver action, the rider's id for a rider action
     * @param price      null when the action carries no price
     * @param rejectCode null when accepted
     */
    public record Row(String runId, String dealId, double tSec, ActorType actorType, String driverId,
                      Action action, Double price, boolean accepted, String rejectCode) {}

    private final String runId;
    private final List<Row> rows = new ArrayList<>();

    public ActionLog(String runId) {
        this.runId = runId;
    }

    public String runId() {
        return runId;
    }

    public void add(String dealId, double tSec, ActorType actorType, String actorId, Action action,
                    Double price, boolean accepted, String rejectCode) {
        rows.add(new Row(runId, dealId, tSec, actorType, actorId, action, price, accepted, rejectCode));
    }

    public List<Row> rows() {
        return List.copyOf(rows);
    }

    public void clear() {
        rows.clear();
    }
}
