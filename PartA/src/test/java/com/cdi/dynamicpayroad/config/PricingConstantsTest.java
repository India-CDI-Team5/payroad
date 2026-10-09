package com.cdi.dynamicpayroad.config;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/** config/pricing-constants.json (card B5, frozen 2026-10-08) and the refusal to start without it. */
class PricingConstantsTest {

    @Test
    void readsTheFrozenRepoFile() {
        PricingConstants p = new PricingConstants("../config/pricing-constants.json");
        assertThat(p.baseFee()).isEqualTo(0.0);
        assertThat(p.perKm()).isEqualTo(18.0);
        assertThat(p.betaCoef()).isEqualTo(0.15);
        assertThat(p.betaCap()).isEqualTo(0.5);
        assertThat(p.uncertaintyWeight()).isEqualTo(0.5);
        assertThat(p.surgeMin()).isEqualTo(0.7);
        assertThat(p.surgeMax()).isEqualTo(3.0);
        assertThat(p.surchargeThreshold()).isEqualTo(1.2);
    }

    @Test
    void missingFileFailsInsteadOfFallingBackToDefaults(@TempDir Path tmp) {
        assertThatThrownBy(() -> new PricingConstants(tmp.resolve("nope.json").toString()))
                .isInstanceOf(IllegalStateException.class).hasMessageContaining("가격 상수 파일 없음");
    }

    @Test
    void missingKeyFails(@TempDir Path tmp) throws IOException {
        Path f = tmp.resolve("p.json");
        Files.writeString(f, "{\"baseFee\": 0, \"perKm\": 18}");
        assertThatThrownBy(() -> new PricingConstants(f.toString()))
                .isInstanceOf(IllegalStateException.class).hasMessageContaining("betaCoef");
    }
}
