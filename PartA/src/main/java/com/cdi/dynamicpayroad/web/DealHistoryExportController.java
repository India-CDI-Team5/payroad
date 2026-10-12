package com.cdi.dynamicpayroad.web;

import com.cdi.dynamicpayroad.model.DealHistory;
import com.cdi.dynamicpayroad.repository.DealHistoryRepository;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.function.Function;

/**
 * User pilot export (card E3): every DealHistory column as CSV, one row per closed deal.
 * Exists only with admin.export-enabled=true; otherwise the path is a plain 404.
 * Rows carry the random participant IDs (R101, DR101-r1, …) and nothing else about a person.
 */
@RestController
@ConditionalOnProperty(name = "admin.export-enabled", havingValue = "true")
public class DealHistoryExportController {

    /** Header name → value, in the CSV column order. Names are the DealHistory field names. */
    static final List<Column> COLUMNS = List.of(
            new Column("id", DealHistory::getId),
            new Column("dealId", DealHistory::getDealId),
            new Column("experimentTag", DealHistory::getExperimentTag),
            new Column("randomSeed", DealHistory::getRandomSeed),
            new Column("userId", DealHistory::getUserId),
            new Column("driverId", DealHistory::getDriverId),
            new Column("createdAt", DealHistory::getCreatedAt),
            new Column("matchedAt", DealHistory::getMatchedAt),
            new Column("endStatus", DealHistory::getEndStatus),
            new Column("endReason", DealHistory::getEndReason),
            new Column("matchPath", DealHistory::getMatchPath),
            new Column("chosenRank", DealHistory::getChosenRank),
            new Column("basePrice", DealHistory::getBasePrice),
            new Column("finalPrice", DealHistory::getFinalPrice),
            new Column("markupRatio", DealHistory::getMarkupRatio),
            new Column("lowestBidPrice", DealHistory::getLowestBidPrice),
            new Column("pickupDistanceKm", DealHistory::getPickupDistanceKm),
            new Column("winningPickupDistanceKm", DealHistory::getWinningPickupDistanceKm),
            new Column("winningPickupEtaMin", DealHistory::getWinningPickupEtaMin),
            new Column("lowestBidPickupDistanceKm", DealHistory::getLowestBidPickupDistanceKm),
            new Column("lowestBidPickupEtaMin", DealHistory::getLowestBidPickupEtaMin),
            new Column("demandInRadius", DealHistory::getDemandInRadius),
            new Column("supplyInRadius", DealHistory::getSupplyInRadius),
            new Column("roundCount", DealHistory::getRoundCount),
            new Column("bidderCount", DealHistory::getBidderCount),
            new Column("withdrawCount", DealHistory::getWithdrawCount),
            new Column("negotiationDurationMs", DealHistory::getNegotiationDurationMs)
    );

    record Column(String name, Function<DealHistory, Object> value) {}

    private final DealHistoryRepository history;

    public DealHistoryExportController(DealHistoryRepository history) {
        this.history = history;
    }

    /** @param tag experimentTag to keep (e.g. "pilot"); omitted = every row. */
    @GetMapping("/api/admin/deal-history.csv")
    public ResponseEntity<String> export(@RequestParam(required = false) String tag) {
        List<DealHistory> rows = tag == null
                ? history.findAllByOrderByIdAsc()
                : history.findByExperimentTagOrderByIdAsc(tag);
        StringBuilder csv = new StringBuilder();
        csv.append(String.join(",", COLUMNS.stream().map(Column::name).toList())).append("\r\n");
        for (DealHistory h : rows) {
            csv.append(String.join(",", COLUMNS.stream().map(c -> cell(c.value().apply(h))).toList())).append("\r\n");
        }
        return ResponseEntity.ok()
                .contentType(new MediaType("text", "csv", StandardCharsets.UTF_8))
                .body(csv.toString());
    }

    /** RFC 4180: null → empty, quote a value that holds a comma, quote or line break. */
    static String cell(Object v) {
        if (v == null) return "";
        String s = v.toString();
        if (s.contains(",") || s.contains("\"") || s.contains("\n") || s.contains("\r")) {
            return "\"" + s.replace("\"", "\"\"") + "\"";
        }
        return s;
    }
}
