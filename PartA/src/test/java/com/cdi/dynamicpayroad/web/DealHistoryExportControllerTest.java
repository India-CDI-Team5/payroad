package com.cdi.dynamicpayroad.web;

import com.cdi.dynamicpayroad.model.DealHistory;
import com.cdi.dynamicpayroad.repository.DealHistoryRepository;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpStatus;

import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Card E3: the pilot CSV export. With the flag on, ?tag= keeps one experimentTag and every
 * DealHistory column is in the header; with the flag off (the default) the controller does not exist.
 */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {"spring.datasource.url=jdbc:h2:mem:export", "admin.export-enabled=true"})
class DealHistoryExportControllerTest {

    @Autowired TestRestTemplate rest;
    @Autowired DealHistoryRepository history;

    @Test
    void exportsOnlyTheTaggedRowsAndOnlyWhenEnabled() {
        history.deleteAll();
        Instant t = Instant.parse("2026-10-17T05:00:00Z");
        history.save(new DealHistory("R101", "DR101-r1", t, 1.5, 3, 5, 100.0, 110.0, 1.1, 2, 2, 40_000, "pilot", null));
        history.save(new DealHistory("R102", "DR102-r1", t, 2.0, 3, 5, 100.0, 95.0, 0.95, 3, 3, 50_000, "live", null));
        history.save(new DealHistory("R103", "DR103-r1", t, 2.5, 3, 5, 100.0, 90.0, 0.9, 1, 1, 30_000, "pi,lot", null));

        var r = rest.getForEntity("/api/admin/deal-history.csv?tag=pilot", String.class);
        assertThat(r.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(r.getHeaders().getContentType().toString()).startsWith("text/csv");
        String[] lines = r.getBody().split("\r\n");
        assertThat(lines[0].split(",")).hasSize(DealHistoryExportController.COLUMNS.size())
                .contains("dealId", "endStatus", "matchPath", "chosenRank", "finalPrice", "lowestBidPrice",
                        "winningPickupEtaMin", "lowestBidPickupEtaMin", "basePrice", "experimentTag");
        assertThat(lines).hasSize(2);
        assertThat(lines[1]).contains(",pilot,").contains("R101").contains("DR101-r1");

        // No tag: every row, and a value holding a comma is quoted.
        String all = rest.getForObject("/api/admin/deal-history.csv", String.class);
        assertThat(all.split("\r\n")).hasSize(4);
        assertThat(all).contains(",\"pi,lot\",");

        // Flag missing (the application.yml default is false): no controller bean, so the path is a 404.
        new ApplicationContextRunner()
                .withBean(DealHistoryRepository.class, () -> Mockito.mock(DealHistoryRepository.class))
                .withUserConfiguration(DealHistoryExportController.class)
                .run(ctx -> assertThat(ctx).doesNotHaveBean(DealHistoryExportController.class));
        new ApplicationContextRunner()
                .withPropertyValues("admin.export-enabled=false")
                .withBean(DealHistoryRepository.class, () -> Mockito.mock(DealHistoryRepository.class))
                .withUserConfiguration(DealHistoryExportController.class)
                .run(ctx -> assertThat(ctx).doesNotHaveBean(DealHistoryExportController.class));
    }
}
