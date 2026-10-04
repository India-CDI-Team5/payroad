package com.cdi.dynamicpayroad.negotiation;

import org.junit.jupiter.api.RepeatedTest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Requires a real local Redis on localhost:6379 (no mocks) — these tests exist
 * specifically to prove the Lua scripts hold up under actual concurrent HTTP-shaped
 * access, not just single-threaded calls. Each test uses fresh UUID-based
 * deal/driver ids so leftover "nego:*" keys from earlier runs never collide.
 */
@SpringBootTest
class NegotiationConcurrencyTest {

    @Autowired
    private NegotiationService service;

    @Test
    void r1_rejectsLessFavorablePriceFromSameDriver() {
        String dealId = service.createDeal("rider-" + UUID.randomUUID(), 100.0);
        String driverId = "driver-" + UUID.randomUUID();

        service.placeBid(dealId, driverId, 90.0);

        NegotiationException ex = assertThrows(NegotiationException.class,
                () -> service.placeBid(dealId, driverId, 95.0));
        assertEquals("PRICE_NOT_CONCEDED", ex.getMessage());
    }

    @Test
    void r13_capsActiveBidsPerDriverAtFifty() {
        String driverId = "driver-" + UUID.randomUUID();

        for (int i = 0; i < 50; i++) {
            String dealId = service.createDeal("rider-" + i, 100.0);
            assertDoesNotThrow(() -> service.placeBid(dealId, driverId, 80.0));
        }

        String overflowDeal = service.createDeal("rider-overflow", 100.0);
        NegotiationException ex = assertThrows(NegotiationException.class,
                () -> service.placeBid(overflowDeal, driverId, 80.0));
        assertEquals("MAX_ACTIVE_BIDS_EXCEEDED", ex.getMessage());
    }

    /**
     * The core correctness claim: a driver with live bids on two deals gets
     * accepted on both at (almost) the same instant. R10 says exactly one
     * must win and the other must find the bid already gone. Repeated 30x
     * with fresh deals each time to make sure this isn't luck.
     */
    @RepeatedTest(30)
    void r9AndR10_exactlyOneOfTwoConcurrentAcceptsWins() throws InterruptedException {
        String driverId = "driver-" + UUID.randomUUID();
        String dealA = service.createDeal("rider-A-" + UUID.randomUUID(), 100.0);
        String dealB = service.createDeal("rider-B-" + UUID.randomUUID(), 100.0);
        service.placeBid(dealA, driverId, 80.0);
        service.placeBid(dealB, driverId, 80.0);

        ExecutorService pool = Executors.newFixedThreadPool(2);
        CountDownLatch startGate = new CountDownLatch(1);
        AtomicInteger succeeded = new AtomicInteger(0);
        AtomicInteger failed = new AtomicInteger(0);

        Runnable acceptOnA = () -> raceAccept(dealA, driverId, startGate, succeeded, failed);
        Runnable acceptOnB = () -> raceAccept(dealB, driverId, startGate, succeeded, failed);

        var f1 = pool.submit(acceptOnA);
        var f2 = pool.submit(acceptOnB);
        startGate.countDown(); // release both threads at (almost) the same instant
        pool.shutdown();
        awaitAll(f1, f2);

        assertEquals(1, succeeded.get(), "정확히 한 건만 체결되어야 한다 (R9)");
        assertEquals(1, failed.get(), "나머지 한 건은 R10에 의해 이미 정리된 호가를 만나 실패해야 한다");
    }

    private void raceAccept(String dealId, String driverId, CountDownLatch startGate,
                             AtomicInteger succeeded, AtomicInteger failed) {
        try {
            startGate.await();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        try {
            service.acceptBid(dealId, driverId);
            succeeded.incrementAndGet();
        } catch (NegotiationException e) {
            assertEquals("BID_NOT_FOUND", e.getMessage(),
                    "지는 쪽은 R10이 정리한 BID_NOT_FOUND여야 한다 (다른 사유로 실패하면 버그)");
            failed.incrementAndGet();
        }
    }

    private void awaitAll(java.util.concurrent.Future<?>... futures) {
        for (var f : futures) {
            try {
                f.get();
            } catch (Exception e) {
                throw new RuntimeException(e);
            }
        }
    }
}
