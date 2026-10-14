package com.cdi.dynamicpayroad.experiment;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/** --offer-base (paper-revision-v1 X3): e1 only, absent by default. */
class ScenarioConfigTest {

    @Test
    void offerBaseIsParsedForE1() {
        assertThat(ScenarioConfig.parse("--scenario", "e1", "--offer-base", "0.9").offerBase()).isEqualTo(0.9);
        assertThat(ScenarioConfig.parse("--scenario", "e1").offerBase()).isNull();
    }

    @Test
    void offerBaseIsRejectedOutsideE1() {
        assertThatThrownBy(() -> ScenarioConfig.parse("--scenario", "e2", "--offer-base", "0.9"))
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("only for e1");
        assertThatThrownBy(() -> ScenarioConfig.parse("--scenario", "e1", "--offer-base", "x"))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
