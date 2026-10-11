package com.cdi.dynamicpayroad.experiment;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/** E7 (card C5) on the test DB (15): run cells, the shared share-0 baseline, and its independence from the strategy. */
class E7ScenarioTest {

    static final String REDIS = System.getProperty("payroad.test.redis-url", "redis://localhost:6379/15");

    private static List<String> deals(Path out, String... args) throws IOException {
        String[] base = {"--scenario", "e7", "--config", "C1", "--seed", "1", "--deals-per-run", "20",
                "--redis-url", REDIS, "--raw-out", out.toString()};
        String[] all = new String[base.length + args.length];
        System.arraycopy(base, 0, all, 0, base.length);
        System.arraycopy(args, 0, all, base.length, args.length);
        ExperimentRunner.run(all);
        return Files.readAllLines(out.resolve("deals_out.csv"));
    }

    @Test
    void defaultCellsAreOneBaselinePlusStrategyTimesShare(@TempDir Path tmp) throws IOException {
        List<String> lines = deals(tmp.resolve("a"));
        assertThat(lines).hasSize(1 + 13 * 20);
        List<String> runs = lines.subList(1, lines.size()).stream().map(l -> l.split(",", 2)[0]).distinct().toList();
        assertThat(runs).hasSize(13);
        assertThat(runs.get(0)).isEqualTo("e7-C1-r0.0-s1");
        assertThat(runs).contains("e7-C1-S1-r0.1-s1", "e7-C1-S4-r0.5-s1").noneMatch(r -> r.contains("-S5-"));
        assertThat(lines.subList(1, lines.size())).allMatch(l -> l.split(",")[4].equals("5")); // n_drivers
    }

    /** Ring share 0 gives the same deals whatever the strategy, so one baseline run per config × seed is enough. */
    @Test
    void shareZeroIsTheSameForEveryStrategyAndEqualsE2(@TempDir Path tmp) throws IOException {
        List<String> first = null;
        for (String s : List.of("S1", "S2", "S3", "S4")) {
            List<String> lines = deals(tmp.resolve(s), "--strategy", s, "--ring-shares", "0");
            if (first == null) first = lines;
            else assertThat(lines).isEqualTo(first);
        }
        ExperimentRunner.run("--scenario", "e2", "--config", "C1", "--seed", "1", "--deals-per-run", "20",
                "--redis-url", REDIS, "--raw-out", tmp.resolve("e2").toString());
        List<String> e2 = Files.readAllLines(tmp.resolve("e2").resolve("deals_out.csv"));
        assertThat(first).hasSameSizeAs(e2);
        for (int i = 1; i < first.size(); i++) {
            String[] x = first.get(i).split(",", -1), y = e2.get(i).split(",", -1);
            assertThat(List.of(x).subList(2, x.length)).isEqualTo(List.of(y).subList(2, y.length));
        }
    }

    /** A colluding share changes the deals, and the same seed keeps the same deal order. */
    @Test
    void ringChangesOutcomesOnTheSameDeals(@TempDir Path tmp) throws IOException {
        List<String> base = deals(tmp.resolve("b"), "--strategy", "S1", "--ring-shares", "0");
        List<String> ring = deals(tmp.resolve("r"), "--strategy", "S1", "--ring-shares", "0.5");
        assertThat(ring).hasSameSizeAs(base);
        int changed = 0;
        for (int i = 1; i < base.size(); i++) {
            String[] x = base.get(i).split(",", -1), y = ring.get(i).split(",", -1);
            assertThat(y[6]).isEqualTo(x[6]); // deal_id
            if (!List.of(x).subList(12, x.length).equals(List.of(y).subList(12, y.length))) changed++;
        }
        assertThat(changed).isGreaterThan(0);
    }
}
