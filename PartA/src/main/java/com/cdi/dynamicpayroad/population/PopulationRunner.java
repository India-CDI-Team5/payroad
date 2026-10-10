package com.cdi.dynamicpayroad.population;

import com.cdi.dynamicpayroad.redis.RedisMarket;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Clock;

/** Starts the virtual population (api-spec §6.7) at boot and steps it once a second. Off in JUnit. */
@Component
@ConditionalOnProperty(prefix = "population", name = "enabled", havingValue = "true", matchIfMissing = true)
@EnableConfigurationProperties(PopulationProperties.class)
public class PopulationRunner implements ApplicationRunner {

    private final PopulationSimulator simulator;

    public PopulationRunner(PopulationProperties props, RedisMarket redisMarket, Clock clock) {
        this.simulator = new PopulationSimulator(props, redisMarket, clock);
    }

    @Override
    public void run(ApplicationArguments args) {
        simulator.start();
    }

    @Scheduled(fixedRate = 1000)
    public void step() {
        simulator.step();
    }
}
