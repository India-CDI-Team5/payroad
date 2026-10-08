package com.cdi.dynamicpayroad.experiment;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;

/**
 * The experiment's deal list, {@code data/experiment/deals.csv} (card B10, ml-design v5 §6.1).
 * Columns are found by header name, not position; extra columns are ignored.
 */
public final class DealSource {

    public static final Path DEFAULT_PATH = Path.of("../data/experiment/deals.csv");

    public record DealRow(String dealId, double distanceKm, double originLat, double originLng,
                          double baseDry, double beta, double basePrice, boolean wet) {}

    private final List<DealRow> rows;

    private DealSource(List<DealRow> rows) {
        this.rows = List.copyOf(rows);
    }

    public static DealSource read(Path path) {
        List<String> lines;
        try {
            lines = Files.readAllLines(path, StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new UncheckedIOException("cannot read deals CSV: " + path, e);
        }
        if (lines.isEmpty()) throw new IllegalArgumentException("empty deals CSV: " + path);

        String header = lines.get(0);
        if (header.startsWith("﻿")) header = header.substring(1);
        Map<String, Integer> col = new HashMap<>();
        String[] names = header.split(",", -1);
        for (int i = 0; i < names.length; i++) col.put(names[i].trim(), i);
        int id = need(col, "deal_id", path), dist = need(col, "distance_km", path),
                lat = need(col, "origin_lat", path), lng = need(col, "origin_lng", path),
                dry = need(col, "base_dry", path), beta = need(col, "beta", path),
                price = need(col, "base_price", path), wet = need(col, "wet", path);

        List<DealRow> rows = new ArrayList<>();
        for (int n = 1; n < lines.size(); n++) {
            String line = lines.get(n);
            if (line.isBlank()) continue;
            String[] f = line.split(",", -1);
            if (f.length != names.length) {
                throw new IllegalArgumentException(path + " line " + (n + 1) + ": expected " + names.length
                        + " fields, got " + f.length);
            }
            rows.add(new DealRow(f[id].trim(), num(f[dist]), num(f[lat]), num(f[lng]), num(f[dry]),
                    num(f[beta]), num(f[price]), bool(f[wet])));
        }
        if (rows.isEmpty()) throw new IllegalArgumentException("no deals in " + path);
        return new DealSource(rows);
    }

    public List<DealRow> rows() {
        return rows;
    }

    /** The rows in the order {@code Collections.shuffle(copy, new Random(seed))} gives. */
    public List<DealRow> shuffled(long seed) {
        List<DealRow> copy = new ArrayList<>(rows);
        Collections.shuffle(copy, new Random(seed));
        return copy;
    }

    private static int need(Map<String, Integer> col, String name, Path path) {
        Integer i = col.get(name);
        if (i == null) throw new IllegalArgumentException(path + ": missing column " + name);
        return i;
    }

    private static double num(String s) {
        return Double.parseDouble(s.trim());
    }

    private static boolean bool(String s) {
        String v = s.trim();
        return v.equals("1") || v.equalsIgnoreCase("true");
    }
}
