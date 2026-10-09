package com.cdi.dynamicpayroad.experiment;

import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Every bot scenario with one seed and 20 deals per run, on the test DB (15): fixed columns,
 * the expected number of rows, and the same bytes twice.
 */
class ScenarioSmokeTest {

    static final String REDIS = System.getProperty("payroad.test.redis-url", "redis://localhost:6379/15");

    /** rows = configs × sweep cells × 20 deals × variants. */
    @ParameterizedTest
    @CsvSource({"e1, 800", "e2, 80", "e3, 160", "e4, 1280", "e5, 240", "e6, 160"})
    void scenarioWritesFixedColumnsAndTheSameBytesTwice(String scenario, int rows, @TempDir Path tmp) throws IOException {
        Path a = tmp.resolve("a"), b = tmp.resolve("b");
        for (Path out : List.of(a, b)) {
            ExperimentRunner.RunSummary s = ExperimentRunner.run("--scenario", scenario, "--seed", "1",
                    "--deals-per-run", "20", "--redis-url", REDIS, "--raw-out", out.toString());
            assertThat(s.episodes()).isEqualTo(rows);
        }

        List<String> lines = Files.readAllLines(a.resolve("deals_out.csv"));
        assertThat(lines.get(0)).isEqualTo(String.join(",", CsvExporter.DEAL_COLUMNS));
        assertThat(CsvExporter.DEAL_COLUMNS.subList(CsvExporter.DEAL_COLUMNS.size() - 2, CsvExporter.DEAL_COLUMNS.size()))
                .containsExactly("mode", "beta_mode");
        assertThat(lines).hasSize(rows + 1);
        assertThat(Files.readAllBytes(b.resolve("deals_out.csv"))).isEqualTo(Files.readAllBytes(a.resolve("deals_out.csv")));
        assertThat(Files.readAllBytes(b.resolve("labels.csv"))).isEqualTo(Files.readAllBytes(a.resolve("labels.csv")));

        List<Map<String, String>> deals = read(lines);
        for (Map<String, String> d : deals) {
            assertThat(d.get("seed")).isEqualTo("1");
            assertThat(d.get("status")).isIn("MATCHED", "EXPIRED", "CANCELLED");
            assertThat(d).containsKeys(CsvExporter.DEAL_COLUMNS.toArray(String[]::new));
        }
        switch (scenario) {
            case "e1" -> assertThat(deals.stream().map(d -> d.get("n_drivers")).distinct())
                    .containsExactly("1", "2", "3", "4", "5", "6", "7", "8", "9", "10");
            case "e3" -> pairedBy(deals, "mode", "bargain", "fixed");
            case "e4" -> assertThat(deals.stream().map(d -> d.get("param_offer_ttl") + "/" + d.get("param_round_limit"))
                    .distinct()).hasSize(16);
            case "e5" -> assertThat(deals.stream().map(d -> d.get("param_tau")).distinct())
                    .containsExactly("0.0000", "0.0200", "0.0500");
            case "e6" -> {
                pairedBy(deals, "beta_mode", "on", "off");
                assertThat(deals).allMatch(d -> d.get("wet").equals("1"));
                assertThat(deals).filteredOn(d -> d.get("beta_mode").equals("off"))
                        .allMatch(d -> d.get("base_price").equals(d.get("base_dry")));
            }
            default -> assertThat(deals).allMatch(d -> d.get("mode").isEmpty() && d.get("beta_mode").isEmpty());
        }
    }

    /** Consecutive rows are the same deal played as {@code first} then {@code second}. */
    private static void pairedBy(List<Map<String, String>> deals, String col, String first, String second) {
        for (int i = 0; i < deals.size(); i += 2) {
            Map<String, String> x = deals.get(i), y = deals.get(i + 1);
            assertThat(x.get(col)).isEqualTo(first);
            assertThat(y.get(col)).isEqualTo(second);
            assertThat(y.get("deal_id")).isEqualTo(x.get("deal_id"));
            assertThat(y.get("deal_index")).isEqualTo(x.get("deal_index"));
            assertThat(y.get("run_id")).isEqualTo(x.get("run_id"));
        }
    }

    private static List<Map<String, String>> read(List<String> lines) {
        String[] header = lines.get(0).split(",", -1);
        List<Map<String, String>> out = new ArrayList<>();
        for (String line : lines.subList(1, lines.size())) {
            String[] f = line.split(",", -1);
            assertThat(f).hasSameSizeAs(header);
            Map<String, String> m = new LinkedHashMap<>();
            for (int i = 0; i < header.length; i++) m.put(header[i], f[i]);
            out.add(m);
        }
        return out;
    }
}
