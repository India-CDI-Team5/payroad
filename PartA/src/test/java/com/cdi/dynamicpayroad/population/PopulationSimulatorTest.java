package com.cdi.dynamicpayroad.population;

import com.cdi.dynamicpayroad.deal.DealService;
import com.cdi.dynamicpayroad.market.SupplyDemandService;
import com.cdi.dynamicpayroad.redis.RedisTestSupport;
import com.cdi.dynamicpayroad.repository.DealHistoryRepository;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Constructor;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Arrays;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;

import static org.assertj.core.api.Assertions.assertThat;

/** The virtual population (api-spec §6.7) on a real Redis (DB 15) with a fixed clock, default properties. */
class PopulationSimulatorTest extends RedisTestSupport {

    static final Clock CLOCK = Clock.fixed(Instant.parse("2026-10-01T00:00:00Z"), ZoneOffset.UTC);

    PopulationSimulator newSimulator() {
        return new PopulationSimulator(new PopulationProperties(), market, CLOCK);
    }

    Set<String> onlineIds() {
        Set<String> ids = new TreeSet<>(cmd.zrange("geo:riders", 0, -1));
        ids.addAll(cmd.zrange("geo:drivers", 0, -1));
        return ids;
    }

    @Test
    void startLogsOnExactlyFivePercentOfUsersAndSeventyPercentOfDrivers() {
        newSimulator().start();

        assertThat(cmd.zcard("geo:riders")).isEqualTo(50);
        assertThat(cmd.zcard("geo:drivers")).isEqualTo(140);
        assertThat(cmd.zcard("presence:expiry")).isEqualTo(190);
    }

    @Test
    void sameSeedGivesTheSameOnlineSet() {
        newSimulator().start();
        Set<String> first = onlineIds();

        market.flushDb();
        newSimulator().start();

        assertThat(first).hasSize(190);
        assertThat(onlineIds()).isEqualTo(first);
    }

    @Test
    void onlineSharesStayNearTheTargetsOver600Steps() {
        PopulationSimulator sim = newSimulator();
        sim.start();

        double users = 0, drivers = 0;
        for (int i = 0; i < 600; i++) {
            sim.step();
            users += cmd.zcard("geo:riders");
            drivers += cmd.zcard("geo:drivers");
        }

        assertThat(users / 600 / 1000).isBetween(0.04, 0.06);
        assertThat(drivers / 600 / 200).isBetween(0.65, 0.75);
        // Redis and the simulator agree on who is online.
        assertThat(cmd.zcard("geo:riders")).isEqualTo(sim.onlineUsers());
        assertThat(cmd.zcard("geo:drivers")).isEqualTo(sim.onlineDrivers());
    }

    @Test
    void hasNoWayToCreateDeals() {
        List<Class<?>> params = Arrays.stream(PopulationSimulator.class.getConstructors())
                .map(Constructor::getParameterTypes)
                .flatMap(Arrays::stream)
                .toList();

        assertThat(params).doesNotContain(DealHistoryRepository.class, DealService.class);
    }

    @Test
    void feedsSupplyAndDemandAtTheCentre() {
        newSimulator().start();

        SupplyDemandService.Snapshot s = new SupplyDemandService(market).at(12.9716, 77.5946);

        assertThat(s.demand()).isPositive();
        assertThat(s.supply()).isPositive();
        assertThat(cmd.keys("deal:*")).isEmpty();
    }
}
