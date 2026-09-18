package com.cdi.dynamicpayroad;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class DynamicPayroadApplication {
    public static void main(String[] args) {
        SpringApplication.run(DynamicPayroadApplication.class, args);
    }
}
