package com.cdi.dynamicpayroad.engine;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class MatchingEngineTest {

    @Test
    @DisplayName("공급 0은 1로 센다: 빈 지역은 최대 할증이 아니라 하한, 수요만 있으면 수요 배수")
    void emptySupplyIsNotAMaximumSurge() {
        assertThat(MatchingEngine.surge(0, 0)).isEqualTo(0.7);   // nobody around: floor, was 3.0
        assertThat(MatchingEngine.surge(2, 0)).isEqualTo(2.0);   // 2 riders, no driver: 2 / 1
        assertThat(MatchingEngine.surge(9, 0)).isEqualTo(3.0);   // still capped
    }

    @Test
    @DisplayName("수요/공급 비율을 0.7~3.0으로 자르고 0.1 단위로 반올림")
    void ratioClampedAndRounded() {
        assertThat(MatchingEngine.surge(3, 3)).isEqualTo(1.0);
        assertThat(MatchingEngine.surge(1, 10)).isEqualTo(0.7);
        assertThat(MatchingEngine.surge(40, 10)).isEqualTo(3.0);
        assertThat(MatchingEngine.surge(7, 3)).isEqualTo(2.3);
    }
}
