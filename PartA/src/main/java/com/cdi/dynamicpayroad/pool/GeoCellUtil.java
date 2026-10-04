package com.cdi.dynamicpayroad.pool;

import java.util.ArrayList;
import java.util.List;

/**
 * Splits the single city-wide GEO set into a grid of cells so a 5km-radius
 * query only has to touch the entities near it, not everyone online. Cell
 * size is chosen bigger than the search radius so the query's own cell plus
 * its 8 neighbors are guaranteed to fully contain every point within
 * RADIUS_KM of any location inside the center cell — full-radius correctness
 * is preserved (nobody in range is skipped), only the per-query working set
 * shrinks.
 */
public final class GeoCellUtil {
    /** ~6.6km at this latitude — bigger than the 5km search radius used by
     *  MatchingEngine, which is what makes the 3x3 neighborhood safe. */
    public static final double CELL_SIZE_DEG = 0.06;

    private GeoCellUtil() {}

    public static String cellKeyFor(double lon, double lat) {
        return cellIndex(lon) + ":" + cellIndex(lat);
    }

    /** The point's own cell plus its 8 neighbors (3x3), as ready-to-use key suffixes. */
    public static List<String> neighborCellKeys(double lon, double lat) {
        long cellLon = cellIndex(lon);
        long cellLat = cellIndex(lat);
        List<String> keys = new ArrayList<>(9);
        for (long dLon = -1; dLon <= 1; dLon++) {
            for (long dLat = -1; dLat <= 1; dLat++) {
                keys.add((cellLon + dLon) + ":" + (cellLat + dLat));
            }
        }
        return keys;
    }

    private static long cellIndex(double degrees) {
        return (long) Math.floor(degrees / CELL_SIZE_DEG);
    }
}
