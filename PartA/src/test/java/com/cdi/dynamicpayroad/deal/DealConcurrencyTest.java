package com.cdi.dynamicpayroad.deal;

import com.cdi.dynamicpayroad.domain.Deal;
import com.cdi.dynamicpayroad.domain.DealCommand;
import com.cdi.dynamicpayroad.domain.DealStatus;
import com.cdi.dynamicpayroad.model.DealHistory;
import com.cdi.dynamicpayroad.presence.PresenceService;
import com.cdi.dynamicpayroad.redis.RedisMarket;
import com.cdi.dynamicpayroad.repository.DealHistoryRepository;
import com.sun.net.httpserver.HttpServer;
import io.lettuce.core.api.StatefulRedisConnection;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.net.InetSocketAddress;
import java.time.Clock;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Concurrency of the live service on Redis (card A6): DealService in a real Spring context
 * (Redis DB 15, H2 in memory), commands sent from several threads at the same instant.
 * The Lua scripts must give exactly one match per deal (R9), one match per driver (R10) and
 * at most 50 live bids per driver (R13). Every attempt uses new deal and driver ids.
 */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "spring.datasource.url=jdbc:h2:mem:dealconcurrency")
class DealConcurrencyTest {

    static final int S_A = 200, S_B = 200, S_C = 20;
    static final int S_C_DEALS = 60, S_C_THREADS = 8, MAX_ACTIVE_BIDS = 50;
    static final double O_LAT = 12.9716, O_LNG = 77.5946, D_LAT = 12.9352, D_LNG = 77.6245;

    static final AtomicInteger passA = new AtomicInteger(), passB = new AtomicInteger(), passC = new AtomicInteger();
    static final AtomicInteger doubleMatches = new AtomicInteger(), maxActiveBids = new AtomicInteger();

    /**
     * Stand-in for Part B /quote that answers 500 at once, so deals open at the fallback price.
     * Without it every create waits ~2 s for Windows to refuse port 8000 (1,800 creates here).
     */
    static final HttpServer QUOTE = quoteStub();

    @DynamicPropertySource
    static void quoteUrl(DynamicPropertyRegistry r) {
        r.add("quote.base-url", () -> "http://127.0.0.1:" + QUOTE.getAddress().getPort());
    }

    @Autowired DealService deals;
    @Autowired PresenceService presence;
    @Autowired DealHistoryRepository history;
    @Autowired RedisMarket redisMarket;
    @Autowired StatefulRedisConnection<String, String> redis;
    @Autowired Clock clock;

    ExecutorService threads;

    @BeforeEach
    void setUp() {
        redisMarket.flushDb();
        threads = Executors.newFixedThreadPool(S_C_THREADS);
    }

    @AfterEach
    void tearDown() throws InterruptedException {
        threads.shutdownNow();
        threads.awaitTermination(10, TimeUnit.SECONDS);
    }

    @AfterAll
    static void report() {
        QUOTE.stop(0);
        System.out.printf("S-A %d/%d, S-B %d/%d, S-C %d/%d, double matches %d, max active bids %d%n",
                passA.get(), S_A, passB.get(), S_B, passC.get(), S_C, doubleMatches.get(), maxActiveBids.get());
    }

    @Test
    void sA_riderPickAndDriverTakeAtOnce_exactlyOneMatch() throws Exception {
        for (int i = 0; i < S_A; i++) {
            String rider = "RA-" + i, d1 = "DA1-" + i, d2 = "DA2-" + i;
            String dealId = open(rider);
            double base = deal(dealId).basePrice();
            presence.registerDriver(d1, O_LAT + 0.001, O_LNG);
            presence.registerDriver(d2, O_LAT, O_LNG + 0.001);
            assertThat(deals.handle(dealId, new DealCommand.PlaceBid(d1, base * 1.2, O_LAT + 0.001, O_LNG, null))).isNull();
            assertThat(deals.handle(dealId, new DealCommand.PlaceBid(d2, base * 1.3, O_LAT, O_LNG + 0.001, null))).isNull();
            assertThat(deals.handle(dealId, new DealCommand.PostOffer(rider, base, null))).isNull();
            String bid1 = bidOf(deal(dealId), d1);

            List<Map<String, Object>> r = together(List.of(
                    () -> deals.handle(dealId, new DealCommand.AcceptBid(rider, bid1, null)),
                    () -> deals.handle(dealId, new DealCommand.AcceptOffer(d2, null))));

            assertThat(r).as("attempt %d", i).filteredOn(x -> x == null).hasSize(1);
            assertThat(r).as("attempt %d", i).filteredOn(x -> x != null).singleElement()
                    .satisfies(e -> assertThat(e).containsEntry("code", "DEAL_ALREADY_MATCHED"));
            assertThat(deal(dealId).status()).isEqualTo(DealStatus.MATCHED);
            long rows = rows(Set.of(dealId)).size();
            if (rows > 1) doubleMatches.incrementAndGet();
            assertThat(rows).as("DealHistory rows of %s", dealId).isEqualTo(1);
            passA.incrementAndGet();
        }
    }

    @Test
    void sB_twoRidersPickTheSameDriverAtOnce_exactlyOneMatch() throws Exception {
        for (int i = 0; i < S_B; i++) {
            String riderX = "RBX-" + i, riderY = "RBY-" + i, driver = "DB-" + i;
            String x = open(riderX), y = open(riderY);
            presence.registerDriver(driver, O_LAT + 0.001, O_LNG);
            for (String id : List.of(x, y)) {
                double base = deal(id).basePrice();
                assertThat(deals.handle(id, new DealCommand.PlaceBid(driver, base * 1.2, O_LAT + 0.001, O_LNG, null))).isNull();
            }
            String bidX = bidOf(deal(x), driver), bidY = bidOf(deal(y), driver);

            // version = null: R10 raises the other deal's version, which would answer VERSION_CONFLICT first.
            List<Map<String, Object>> r = together(List.of(
                    () -> deals.handle(x, new DealCommand.AcceptBid(riderX, bidX, null)),
                    () -> deals.handle(y, new DealCommand.AcceptBid(riderY, bidY, null))));

            assertThat(r).as("attempt %d", i).filteredOn(e -> e == null).hasSize(1);
            assertThat(r).as("attempt %d", i).filteredOn(e -> e != null).singleElement()
                    .satisfies(e -> assertThat(e).containsEntry("code", "BID_NOT_FOUND"));
            List<DealStatus> statuses = List.of(deal(x).status(), deal(y).status());
            assertThat(statuses).as("attempt %d", i).containsOnlyOnce(DealStatus.MATCHED);
            long won = rows(Set.of(x, y)).stream().filter(h -> driver.equals(h.getDriverId())).count();
            if (won > 1) doubleMatches.incrementAndGet();
            assertThat(won).as("DealHistory rows won by %s", driver).isEqualTo(1);
            passB.incrementAndGet();
        }
    }

    @Test
    void sC_oneDriverBidsOn60DealsFrom8Threads_exactly50Live() throws Exception {
        for (int i = 0; i < S_C; i++) {
            String driver = "DC-" + i;
            List<String> ids = new ArrayList<>(S_C_DEALS);
            for (int k = 0; k < S_C_DEALS; k++) ids.add(open("RC-" + i + "-" + k));
            presence.registerDriver(driver, O_LAT + 0.001, O_LNG);
            Map<String, Double> base = new HashMap<>();
            for (String id : ids) base.put(id, deal(id).basePrice());

            // Thread t takes deals t, t + 8, t + 16, ...; all threads start together.
            List<Callable<List<Map<String, Object>>>> work = new ArrayList<>();
            for (int t = 0; t < S_C_THREADS; t++) {
                int first = t;
                work.add(() -> {
                    List<Map<String, Object>> out = new ArrayList<>();
                    for (int k = first; k < ids.size(); k += S_C_THREADS) {
                        String id = ids.get(k);
                        out.add(deals.handle(id, new DealCommand.PlaceBid(driver, base.get(id) * 1.2, O_LAT + 0.001, O_LNG, null)));
                    }
                    return out;
                });
            }
            List<Map<String, Object>> r = together(work).stream().flatMap(List::stream).toList();

            assertThat(r).hasSize(S_C_DEALS);
            assertThat(r).as("attempt %d accepted", i).filteredOn(e -> e == null).hasSize(MAX_ACTIVE_BIDS);
            assertThat(r).as("attempt %d rejected", i).filteredOn(e -> e != null)
                    .hasSize(S_C_DEALS - MAX_ACTIVE_BIDS)
                    .allSatisfy(e -> assertThat(e).containsEntry("code", "MAX_ACTIVE_BIDS_EXCEEDED"));
            long live = redis.sync().scard("driver:" + driver + ":deals");
            maxActiveBids.accumulateAndGet((int) live, Math::max);
            assertThat(live).isEqualTo(MAX_ACTIVE_BIDS);
            passC.incrementAndGet();
        }
    }

    // --- helpers -------------------------------------------------------------------------------

    private String open(String riderId) {
        return (String) deals.create(riderId, O_LAT, O_LNG, D_LAT, D_LNG).get("dealId");
    }

    private Deal deal(String dealId) {
        return redisMarket.snapshot(dealId, clock.instant()).orElseThrow().deal();
    }

    private static String bidOf(Deal d, String driverId) {
        return d.bids().stream().filter(b -> b.driverId().equals(driverId)).findFirst().orElseThrow().bidId();
    }

    private List<DealHistory> rows(Set<String> dealIds) {
        return history.findAll().stream().filter(h -> h.getDealId() != null && dealIds.contains(h.getDealId())).toList();
    }

    /** Runs every task on its own pool thread, released by one latch once all are waiting. */
    private <T> List<T> together(List<Callable<T>> tasks) throws Exception {
        CountDownLatch ready = new CountDownLatch(tasks.size());
        CountDownLatch go = new CountDownLatch(1);
        List<Future<T>> futures = new ArrayList<>();
        for (Callable<T> task : tasks) {
            futures.add(threads.submit(() -> {
                ready.countDown();
                go.await();
                return task.call();
            }));
        }
        assertThat(ready.await(10, TimeUnit.SECONDS)).as("all threads ready").isTrue();
        go.countDown();
        List<T> out = new ArrayList<>();
        for (Future<T> f : futures) out.add(f.get(30, TimeUnit.SECONDS));
        return out;
    }

    private static HttpServer quoteStub() {
        try {
            HttpServer s = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            s.createContext("/quote", ex -> {
                ex.getRequestBody().readAllBytes();
                ex.sendResponseHeaders(500, -1);
                ex.close();
            });
            s.start();
            return s;
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }
}
