package com.cdi.dynamicpayroad.market;

/** Standard base32 geohash encoding (api-spec §4.4 {@code cells}). */
public final class Geohash {

    private static final String BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz";

    private Geohash() {}

    public static String encode(double lat, double lng, int precision) {
        double[] latRange = {-90.0, 90.0};
        double[] lngRange = {-180.0, 180.0};
        StringBuilder hash = new StringBuilder(precision);
        boolean evenBit = true;   // bits alternate, longitude first
        int bit = 0, ch = 0;
        while (hash.length() < precision) {
            double[] range = evenBit ? lngRange : latRange;
            double value = evenBit ? lng : lat;
            double mid = (range[0] + range[1]) / 2;
            ch <<= 1;
            if (value >= mid) {
                ch |= 1;
                range[0] = mid;
            } else {
                range[1] = mid;
            }
            evenBit = !evenBit;
            if (++bit == 5) {
                hash.append(BASE32.charAt(ch));
                bit = 0;
                ch = 0;
            }
        }
        return hash.toString();
    }
}
