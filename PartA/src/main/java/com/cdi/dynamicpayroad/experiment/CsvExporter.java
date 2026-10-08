package com.cdi.dynamicpayroad.experiment;

import com.cdi.dynamicpayroad.domain.Deal;
import com.cdi.dynamicpayroad.domain.DealRules;
import com.cdi.dynamicpayroad.experiment.Agent.ActorType;
import com.cdi.dynamicpayroad.experiment.DealSource.DealRow;

import java.io.BufferedWriter;
import java.io.Closeable;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Writes the runner's three CSV files: deals_out.csv (one row per episode), actions.csv
 * ({@link ActionLog}) and labels.csv (hidden driver roles, kept apart from the features).
 * Column order is fixed; numbers use Locale.ROOT with 4 decimals (t_sec: 3); lines end with \n.
 */
public final class CsvExporter implements Closeable {

    public static final List<String> DEAL_COLUMNS = List.of(
            "run_id", "scenario", "config", "seed", "n_drivers", "deal_index", "deal_id", "base_price", "base_dry",
            "beta", "wet", "distance_km", "status", "end_reason", "match_path", "final_price", "markup", "markup_dry",
            "chosen_rank", "lowest_bid_price", "winner_id", "winner_strategy", "winner_is_colluder",
            "winner_pickup_eta", "lowest_bid_pickup_eta", "round_count", "bidder_count", "withdraw_count",
            "duration_sec", "param_offer_ttl", "param_round_limit", "param_tau");
    public static final List<String> ACTION_COLUMNS = List.of(
            "run_id", "deal_id", "t_sec", "actor_type", "driver_id", "action", "price", "accepted", "reject_code");
    public static final List<String> LABEL_COLUMNS = List.of("run_id", "driver_id", "is_colluder", "strategy");

    /** What is the same for every episode of one run. {@code tau} is null when the scenario does not fix it. */
    public record RunMeta(String runId, String scenario, String config, long seed, DealRules rules, Double tau) {}

    private final BufferedWriter deals;
    private final BufferedWriter actions;
    private final BufferedWriter labels;

    public CsvExporter(Path dir) {
        try {
            Files.createDirectories(dir);
            deals = open(dir.resolve("deals_out.csv"), DEAL_COLUMNS);
            actions = open(dir.resolve("actions.csv"), ACTION_COLUMNS);
            labels = open(dir.resolve("labels.csv"), LABEL_COLUMNS);
        } catch (IOException e) {
            throw new UncheckedIOException("cannot open output in " + dir, e);
        }
    }

    public void writeDeal(RunMeta run, EpisodeEngine.Result r) {
        DealRow row = r.row();
        Deal d = r.deal();
        Deal.Match m = d.match();
        Agent winner = m == null ? null
                : r.agents().stream().filter(a -> a.id().equals(m.driverId())).findFirst().orElse(null);
        List<String> f = new ArrayList<>(DEAL_COLUMNS.size());
        f.add(run.runId());
        f.add(str(run.scenario()));
        f.add(str(run.config()));
        f.add(Long.toString(run.seed()));
        f.add(Integer.toString(r.driverCount()));
        f.add(Integer.toString(r.dealIndex()));
        f.add(row.dealId());
        f.add(num(row.basePrice()));
        f.add(num(row.baseDry()));
        f.add(num(row.beta()));
        f.add(row.wet() ? "1" : "0");
        f.add(num(row.distanceKm()));
        f.add(d.status().name());
        f.add(d.endReason() == null ? "" : d.endReason().name());
        f.add(m == null ? "" : m.matchPath().name());
        f.add(m == null ? "" : num(m.finalPrice()));
        f.add(m == null ? "" : num(m.finalPrice() / row.basePrice()));
        f.add(m == null ? "" : num(m.finalPrice() / row.baseDry()));
        f.add(m == null ? "" : Integer.toString(m.chosenRank()));
        f.add(m == null ? "" : num(m.lowestBidPrice()));
        f.add(m == null ? "" : m.driverId());
        f.add(winner == null ? "" : winner.strategy());
        f.add(winner == null ? "" : flag(winner.colluder()));
        f.add(m == null ? "" : num(m.pickupEtaMin()));
        f.add(m == null ? "" : num(m.lowestBidPickupEtaMin()));
        f.add(Integer.toString(d.round()));
        f.add(Integer.toString(d.lastBidByDriver().size()));
        f.add(Integer.toString(d.withdrawCount()));
        f.add(num(r.durationSec()));
        f.add(Long.toString(run.rules().offerTtl().toSeconds()));
        f.add(Integer.toString(run.rules().roundLimit()));
        f.add(run.tau() == null ? "" : num(run.tau()));
        line(deals, f);
    }

    /** Writes and clears the log. */
    public void writeActions(ActionLog log) {
        for (ActionLog.Row a : log.rows()) {
            line(actions, List.of(a.runId(), a.dealId(), String.format(Locale.ROOT, "%.3f", a.tSec()),
                    a.actorType().name(), a.driverId(), a.action().name(), num(a.price()),
                    a.accepted() ? "1" : "0", str(a.rejectCode())));
        }
        log.clear();
    }

    /** One row per driver of the run's pool. */
    public void writeLabels(String runId, List<? extends Agent> drivers) {
        for (Agent a : drivers) {
            if (a.actorType() != ActorType.DRIVER) continue;
            line(labels, List.of(runId, a.id(), flag(a.colluder()), a.strategy()));
        }
    }

    @Override
    public void close() {
        IOException first = null;
        for (BufferedWriter w : List.of(deals, actions, labels)) {
            try {
                w.close();
            } catch (IOException e) {
                if (first == null) first = e;
            }
        }
        if (first != null) throw new UncheckedIOException(first);
    }

    private static BufferedWriter open(Path file, List<String> header) throws IOException {
        BufferedWriter w = Files.newBufferedWriter(file, StandardCharsets.UTF_8);
        line(w, header);
        return w;
    }

    private static void line(BufferedWriter w, List<String> fields) {
        try {
            w.write(String.join(",", fields));
            w.write('\n');
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    static String num(Double x) {
        return x == null ? "" : String.format(Locale.ROOT, "%.4f", x);
    }

    private static String str(String s) {
        return s == null ? "" : s;
    }

    private static String flag(boolean b) {
        return b ? "1" : "0";
    }
}
