package com.cdi.dynamicpayroad.experiment;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

/** Same seed, same bytes (plan v6 §3.3). Needs Redis; runs on the test DB (15). */
class DeterminismTest {

    static final String REDIS = System.getProperty("payroad.test.redis-url", "redis://localhost:6379/15");
    static final String DEALS = "src/test/resources/experiment/deals_small.csv";

    @Test
    void smokeWithTheSameSeedWritesIdenticalFiles(@TempDir Path tmp) throws IOException {
        Path a = tmp.resolve("a"), b = tmp.resolve("b");
        ExperimentRunner.run("--scenario", "smoke", "--seed", "7", "--deals", DEALS, "--redis-url", REDIS,
                "--raw-out", a.toString(), "--out", a.toString());
        ExperimentRunner.run("--scenario", "smoke", "--seed", "7", "--deals", DEALS, "--redis-url", REDIS,
                "--raw-out", b.toString(), "--out", b.toString());

        for (String f : new String[] {"deals_out.csv", "actions.csv", "labels.csv"}) {
            byte[] x = Files.readAllBytes(a.resolve(f));
            assertThat(x).as(f).isNotEmpty();
            assertThat(Files.readAllBytes(b.resolve(f))).as(f).isEqualTo(x);
        }
    }

    @Test
    void anotherSeedShufflesTheDealsDifferently(@TempDir Path tmp) throws IOException {
        Path a = tmp.resolve("a"), b = tmp.resolve("b");
        ExperimentRunner.run("--scenario", "smoke", "--seed", "7", "--deals", DEALS, "--redis-url", REDIS,
                "--raw-out", a.toString());
        ExperimentRunner.run("--scenario", "smoke", "--seed", "8", "--deals", DEALS, "--redis-url", REDIS,
                "--raw-out", b.toString());

        assertThat(dealIds(a)).isNotEqualTo(dealIds(b));
    }

    private static String dealIds(Path dir) throws IOException {
        StringBuilder sb = new StringBuilder();
        for (String line : Files.readAllLines(dir.resolve("deals_out.csv")).subList(1, 11)) {
            sb.append(line.split(",", -1)[6]).append(' ');
        }
        return sb.toString();
    }
}
