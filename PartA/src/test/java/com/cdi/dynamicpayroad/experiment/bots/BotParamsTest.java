package com.cdi.dynamicpayroad.experiment.bots;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/** The post-hoc offer_base override (paper-revision-v1 X3) changes nothing but rider.offer_base. */
class BotParamsTest {

    static final BotParams PARAMS = BotParams.read(BotParams.DEFAULT_PATH);

    @Test
    void withOfferBaseChangesOnlyOfferBase() {
        BotParams p = PARAMS.withOfferBase(0.9);
        assertThat(p.rider().offerBase()).isEqualTo(0.9);
        assertThat(PARAMS.rider().offerBase()).isEqualTo(0.80);
        assertThat(p).usingRecursiveComparison().ignoringFields("rider").isEqualTo(PARAMS);
        assertThat(p.rider()).usingRecursiveComparison().ignoringFields("offerBase").isEqualTo(PARAMS.rider());
    }

    @Test
    void offerBaseOutsideRangeIsRejected() {
        assertThatThrownBy(() -> PARAMS.withOfferBase(0.69)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> PARAMS.withOfferBase(1.51)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> PARAMS.withOfferBase(Double.NaN)).isInstanceOf(IllegalArgumentException.class);
    }
}
