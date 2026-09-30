package com.cdi.dynamicpayroad.web;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class RouteControllerTest {

    @Test
    void unquote_strips_matching_surrounding_quotes() {
        assertThat(RouteController.unquote("\"abc=\"")).isEqualTo("abc=");
        assertThat(RouteController.unquote("'abc='")).isEqualTo("abc=");
        assertThat(RouteController.unquote("  \"abc\" ")).isEqualTo("abc");
    }

    @Test
    void unquote_leaves_plain_and_unbalanced_values() {
        assertThat(RouteController.unquote("abc=")).isEqualTo("abc=");
        assertThat(RouteController.unquote("\"abc")).isEqualTo("\"abc");
        assertThat(RouteController.unquote("")).isEqualTo("");
    }
}
