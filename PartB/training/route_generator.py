"""Generate Bengaluru road routes for Model A: origins weighted toward major hubs,
lengths stratified over 5-60 km, each route resampled every 500 m and mapped to weather cells.

ORS is the scarce resource (the current key allows 200 directions per 24 h, see
X-Ratelimit-Limit), so candidates are filtered before calling ORS, responses are cached on
disk, and the run stops before the key's remaining quota drops under --reserve.

Run from PartB/ (after training.meteo_probe has written data/grid_cells.json):
    python -m training.route_generator --n 24 --out data/routes_dryrun.parquet
"""
import argparse
import json
import math
import os
import random
import time
from collections import Counter

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
from diskcache import Cache
from dotenv import load_dotenv

from training.geo import in_bbox, nearest_cell, offset, resample

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
ORS_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
ORS_KEY = os.environ.get("ORS_API_KEY", "")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
ors_cache = Cache(os.path.join(os.path.dirname(__file__), "..", ".cache", "ors_training"))

# Origin hubs and their sampling weights (assumed: central business/residential areas heavier).
HUBS = {
    "MG Road": ((12.9756, 77.6050), 3),
    "Koramangala": ((12.9352, 77.6245), 3),
    "Indiranagar": ((12.9719, 77.6412), 3),
    "Whitefield": ((12.9698, 77.7500), 2),
    "Majestic": ((12.9767, 77.5713), 2),
    "Electronic City": ((12.8452, 77.6602), 2),
    "Jayanagar": ((12.9250, 77.5938), 2),
    "Hebbal": ((13.0358, 77.5970), 2),
    "Yelahanka": ((13.1007, 77.5963), 1),
    "Kempegowda Airport": ((13.1986, 77.7066), 1),
}
ORIGIN_JITTER_KM = 1.5
# Road-length strata (km, lower inclusive) and their share of routes.
STRATA = {"short": (5, 15), "medium": (15, 30), "long": (30, 60)}
DETOUR = 1.35                    # road km / straight km, first guess; measured ratio is reported
STEP_KM = 0.5


def pick_origin(rng):
    names = list(HUBS)
    name = rng.choices(names, weights=[HUBS[n][1] for n in names])[0]
    (lat, lon), _ = HUBS[name]
    lat, lon = offset(lat, lon, abs(rng.gauss(0, ORIGIN_JITTER_KM)), rng.uniform(0, 360))
    return name, lat, lon


def candidate(rng, stratum):
    """Origin/destination pair whose straight-line distance targets the stratum; None if off-map."""
    lo, hi = STRATA[stratum]
    hub, o_lat, o_lon = pick_origin(rng)
    road_km = rng.uniform(lo, hi)
    d_lat, d_lon = offset(o_lat, o_lon, road_km / DETOUR, rng.uniform(0, 360))
    if not in_bbox(o_lat, o_lon) or not in_bbox(d_lat, d_lon):
        return None
    return hub, (o_lat, o_lon), (d_lat, d_lon)


class Ors:
    def __init__(self, client, reserve):
        self.client, self.reserve = client, reserve
        self.calls = 0
        self.limit = self.remaining = None

    def route(self, origin, dest):
        key = f"{origin[0]:.5f},{origin[1]:.5f}:{dest[0]:.5f},{dest[1]:.5f}"
        hit = ors_cache.get(key)
        if hit is not None:
            return hit
        if self.remaining is not None and self.remaining <= self.reserve:
            raise QuotaExhausted(self.remaining)
        body = {"coordinates": [[origin[1], origin[0]], [dest[1], dest[0]]],
                "radiuses": [1000, 1000], "instructions": False}
        r = self.client.post(ORS_URL, json=body, headers={"Authorization": ORS_KEY})
        self.calls += 1
        self.limit = int(r.headers.get("x-ratelimit-limit", self.limit or 0))
        self.remaining = int(r.headers.get("x-ratelimit-remaining", self.remaining or 0))
        time.sleep(1.6)                       # stay under the 40 requests/min burst limit
        if r.status_code == 404 or r.status_code == 400:
            data = {"error": r.status_code}   # no routable point nearby: cache the miss too
        elif r.status_code != 200:
            raise RuntimeError(f"ORS {r.status_code}: {r.text[:200]}")
        else:
            data = r.json()
        ors_cache.set(key, data)
        return data


class QuotaExhausted(Exception):
    pass


def build_record(route_id, stratum, hub, origin, dest, data, cells):
    feat = data["features"][0]
    km = feat["properties"]["summary"]["distance"] / 1000
    minutes = feat["properties"]["summary"]["duration"] / 60
    coords = [(c[1], c[0]) for c in feat["geometry"]["coordinates"]]
    pts = resample(coords, STEP_KM)
    total = pts[-1][2] or 1.0
    cell_ids = [nearest_cell(p[0], p[1], cells) for p in pts]
    return {
        "route_id": route_id, "stratum": stratum, "hub": hub,
        "origin_lat": origin[0], "origin_lon": origin[1], "dest_lat": dest[0], "dest_lon": dest[1],
        "distance_km": round(km, 3), "duration_min": round(minutes, 2),
        "detour_ratio": round(km / max(1e-6, _straight_km(origin, dest)), 3),
        "lat": [p[0] for p in pts], "lon": [p[1] for p in pts],
        "s_km": [round(p[2], 3) for p in pts],
        # Arrival offset along the route, assuming ORS's average speed holds on every segment.
        "t_min": [round(p[2] / total * minutes, 2) for p in pts],
        "cell": cell_ids, "unique_cells": len(set(cell_ids)),
    }


def _straight_km(a, b):
    from training.geo import haversine_km
    return haversine_km(a[0], a[1], b[0], b[1])


def generate(n, seed, reserve):
    with open(os.path.join(DATA_DIR, "grid_cells.json"), encoding="utf-8") as f:
        cells = [tuple(c) for c in json.load(f)["cells"]]
    rng = random.Random(seed)
    quota = {s: n // len(STRATA) + (i < n % len(STRATA)) for i, s in enumerate(STRATA)}
    stats = {s: Counter() for s in STRATA}
    records = []
    stopped = None
    with httpx.Client(timeout=30) as client:
        ors = Ors(client, reserve)
        for stratum, want in quota.items():
            got = 0
            while got < want:
                stats[stratum]["candidates"] += 1
                cand = candidate(rng, stratum)
                if cand is None:
                    stats[stratum]["off_map"] += 1
                    continue
                hub, origin, dest = cand
                try:
                    data = ors.route(origin, dest)
                except QuotaExhausted as e:
                    stopped = f"stopped with {e.args[0]} ORS calls left (reserve {reserve})"
                    break
                stats[stratum]["ors_requests"] += 1
                if "error" in data:
                    stats[stratum]["unroutable"] += 1
                    continue
                km = data["features"][0]["properties"]["summary"]["distance"] / 1000
                lo, hi = STRATA[stratum]
                if not lo <= km < hi:
                    stats[stratum]["wrong_length"] += 1
                    continue
                records.append(build_record(len(records), stratum, hub, origin, dest, data, cells))
                stats[stratum]["accepted"] += 1
                got += 1
            if stopped:
                break
    return records, stats, ors, stopped


def summarize(records, stats, ors, stopped, target_routes):
    by = {}
    for s in STRATA:
        rs = [r for r in records if r["stratum"] == s]
        st = stats[s]
        us = sorted(r["unique_cells"] for r in rs)
        by[s] = {
            "accepted": st["accepted"], "ors_requests": st["ors_requests"],
            "acceptance_per_ors_request": round(st["accepted"] / st["ors_requests"], 3) if st["ors_requests"] else None,
            "off_map_candidates": st["off_map"], "unroutable": st["unroutable"], "wrong_length": st["wrong_length"],
            "unique_cells_min_median_max": [us[0], us[len(us) // 2], us[-1]] if us else None,
            "share_U_ge_3": round(sum(u >= 3 for u in us) / len(us), 3) if us else None,
            "detour_ratio_mean": round(sum(r["detour_ratio"] for r in rs) / len(rs), 3) if rs else None,
            "points_per_route_mean": round(sum(len(r["s_km"]) for r in rs) / len(rs), 1) if rs else None,
        }
    accepted = sum(v["accepted"] for v in by.values())
    requests = sum(v["ors_requests"] for v in by.values())
    rate = accepted / requests if requests else 0
    need = math.ceil(target_routes / rate) if rate else None
    return {
        "strata": by,
        "all": {"accepted": accepted, "ors_requests": requests, "ors_calls_this_run": ors.calls,
                "share_U_ge_3": round(sum(r["unique_cells"] >= 3 for r in records) / len(records), 3) if records else None},
        "ors_key": {"limit": ors.limit, "remaining": ors.remaining},
        "plan": {"target_routes": target_routes, "ors_requests_needed": need,
                 "days_at_key_limit": round(need / ors.limit, 1) if need and ors.limit else None},
        "stopped": stopped,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=24, help="routes to generate, split evenly over strata")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--reserve", type=int, default=30, help="ORS calls to leave unused for the app")
    ap.add_argument("--target", type=int, default=400, help="route count the full collection aims for")
    ap.add_argument("--out", default=os.path.join(DATA_DIR, "routes.parquet"))
    args = ap.parse_args()

    records, stats, ors, stopped = generate(args.n, args.seed, args.reserve)
    if records:
        pq.write_table(pa.Table.from_pylist(records), args.out)
    summary = summarize(records, stats, ors, stopped, args.target)
    with open(os.path.splitext(args.out)[0] + "_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
