"""Small geometry helpers shared by the data-collection scripts (lat/lon in degrees, km)."""
import math

EARTH_RADIUS_KM = 6371.0

# Collection area: Bengaluru urban area plus the airport corridor. Routes must stay inside it.
BBOX = {"lat_min": 12.70, "lat_max": 13.30, "lon_min": 77.35, "lon_max": 77.95}


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def offset(lat, lon, distance_km, bearing_deg):
    """Point reached by travelling distance_km from (lat, lon) on the given bearing."""
    d = distance_km / EARTH_RADIUS_KM
    b = math.radians(bearing_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def in_bbox(lat, lon, bbox=BBOX):
    return bbox["lat_min"] <= lat <= bbox["lat_max"] and bbox["lon_min"] <= lon <= bbox["lon_max"]


def resample(coords_latlon, step_km):
    """Points every step_km along a polyline, always including both ends.

    Returns [(lat, lon, s_km)] where s_km is the distance along the route.
    """
    out = [(coords_latlon[0][0], coords_latlon[0][1], 0.0)]
    travelled, next_mark = 0.0, step_km
    for (a_lat, a_lon), (b_lat, b_lon) in zip(coords_latlon, coords_latlon[1:]):
        seg = haversine_km(a_lat, a_lon, b_lat, b_lon)
        while seg > 0 and travelled + seg >= next_mark:
            f = (next_mark - travelled) / seg
            out.append((a_lat + f * (b_lat - a_lat), a_lon + f * (b_lon - a_lon), next_mark))
            next_mark += step_km
        travelled += seg
    end = coords_latlon[-1]
    if travelled - out[-1][2] > 1e-6:
        out.append((end[0], end[1], travelled))
    return out


def nearest_cell(lat, lon, cells):
    """Index of the grid-cell centre closest to (lat, lon). cells = [(lat, lon), ...]."""
    k = math.cos(math.radians(lat))
    return min(range(len(cells)), key=lambda i: (cells[i][0] - lat) ** 2 + ((cells[i][1] - lon) * k) ** 2)
