package com.cdi.dynamicpayroad.market;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class GeohashTest {

    @Test
    void encodesTheReferencePoint() {
        assertThat(Geohash.encode(57.64911, 10.40744, 5)).isEqualTo("u4pru");
        assertThat(Geohash.encode(57.64911, 10.40744, 11)).isEqualTo("u4pruydqqvj");
    }

    @Test
    void cellsAreTheCentreThenItsEightNeighbours() {
        List<String> cells = MarketController.cells(12.97, 77.59);
        assertThat(cells).hasSize(9).doesNotHaveDuplicates();
        assertThat(cells.get(0)).isEqualTo(Geohash.encode(12.97, 77.59, 5));
        assertThat(cells).allSatisfy(c -> assertThat(c).hasSize(5));
    }
}
