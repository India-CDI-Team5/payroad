package com.cdi.dynamicpayroad.config;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Pricing constants from config/pricing-constants.json (card B5, docs/pricing-constants.md). The
 * JSON is the only source of these values; a missing file or key stops the service from starting.
 */
@Component
public class PricingConstants {

    private final double baseFee;
    private final double perKm;
    private final double betaCoef;
    private final double betaCap;
    private final double uncertaintyWeight;
    private final double surgeMin;
    private final double surgeMax;
    private final double surchargeThreshold;

    public PricingConstants(@Value("${pricing.constants-path:../config/pricing-constants.json}") String path) {
        Path file = Path.of(path);
        if (!Files.isRegularFile(file)) {
            throw new IllegalStateException("가격 상수 파일 없음: " + file.toAbsolutePath());
        }
        JsonNode root;
        try {
            root = new ObjectMapper().readTree(file.toFile());
        } catch (IOException e) {
            throw new IllegalStateException("가격 상수 파일을 읽을 수 없음: " + file.toAbsolutePath(), e);
        }
        baseFee = number(root, "baseFee", file);
        perKm = number(root, "perKm", file);
        betaCoef = number(root, "betaCoef", file);
        betaCap = number(root, "betaCap", file);
        uncertaintyWeight = number(root, "uncertaintyWeight", file);
        surgeMin = number(root, "surgeMin", file);
        surgeMax = number(root, "surgeMax", file);
        surchargeThreshold = number(root, "surchargeThreshold", file);
    }

    public double baseFee() { return baseFee; }
    public double perKm() { return perKm; }
    public double betaCoef() { return betaCoef; }
    public double betaCap() { return betaCap; }
    public double uncertaintyWeight() { return uncertaintyWeight; }
    public double surgeMin() { return surgeMin; }
    public double surgeMax() { return surgeMax; }
    public double surchargeThreshold() { return surchargeThreshold; }

    private static double number(JsonNode root, String key, Path file) {
        JsonNode v = root.get(key);
        if (v == null || !v.isNumber()) {
            throw new IllegalStateException("가격 상수 " + key + " 없음 또는 숫자 아님: " + file.toAbsolutePath());
        }
        return v.doubleValue();
    }
}
