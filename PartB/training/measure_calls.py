"""Call-saving table T3 of the proceedings (card B8), offline: no ORS or Open-Meteo call.

T3_calls.csv, over the 100 held-out routes (routes_holdout.parquet):
  current_points   the old /route-weather: determine_sample_count points, one forecast coordinate each
  current_cells    the same points with duplicate cells removed
  all_cells_U      every cell the route crosses (U)
  proposed_M2      /quote: k = ceil(servingBudgetRatio × U)

T3_cache.csv, cache keys within one 10-minute forecast TTL: 500 random trips (seed 42) between the
five busiest hubs, each trip reusing the main-set route whose origin and destination are nearest to
it. Assumption: all 500 quotes arrive inside one TTL window, so nothing expires and a key repeats
only because another trip asked for it. Rows compare the old points keyed by 2-decimal coordinates
(the current forecast cache key), the same points keyed by their cell centre, and the cells /quote
asks for (keyed by cell centre).

Run from PartB/:  python -m training.measure_calls
"""
import argparse
import csv
import math
import os
import random

import numpy as np
import pyarrow.parquet as pq

from geo import haversine_km, nearest_cell
from pricing.base_price import load_constants
from quote import load_cells, load_model
from sampler import determine_sample_count, sample_route
from training.route_generator import HUBS
from weather.methods import select_m2
from weather.oracle import RouteOracle

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "data")
OUT_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "results", "tables"))
CACHE_HUBS = 5                       # the first five HUBS: the heaviest-weighted origins
CACHE_TRIPS = 500
CACHE_TTL_MIN = 10                   # clients/meteo_client.FORECAST_TTL_SEC
SEED = 42
KEY_DECIMALS = 2                     # clients/meteo_client.FORECAST_KEY_DECIMALS


def load(name):
    return pq.read_table(os.path.join(DATA_DIR, name)).to_pylist()


def current_points(route):
    """The old sampler's points as (lat, lon): determine_sample_count, evenly by distance along the route."""
    n = determine_sample_count(route["distance_km"])
    pts = sample_route([[lon, lat] for lat, lon in zip(route["lat"], route["lon"])], n)
    return [(p[1], p[0]) for p in pts]


def proposed_cells(route, model, ratio):
    oracle = RouteOracle(route["cell"], np.zeros(len(route["cell"])))
    k = max(1, math.ceil(ratio * oracle.U))
    return select_m2(oracle, np.asarray(route["s_km"]), np.asarray(route["t_min"]), k, model)


def call_rows(routes, cells, ratio):
    counts = {"current_points": [], "current_cells": [], "all_cells_U": [], "proposed_M2": []}
    for r in routes:
        pts = current_points(r)
        counts["current_points"].append(len(pts))
        counts["current_cells"].append(len({nearest_cell(p[0], p[1], cells) for p in pts}))
        counts["all_cells_U"].append(len(set(r["cell"])))
        counts["proposed_M2"].append(max(1, math.ceil(ratio * len(set(r["cell"])))))
    base = sum(counts["current_points"])
    return [{"method": m, "routes": len(v), "mean_calls": round(float(np.mean(v)), 3),
             "median_calls": float(np.median(v)), "total_calls": int(sum(v)),
             "saving_vs_current": round(1 - sum(v) / base, 4)} for m, v in counts.items()]


def nearest_route(routes, a, b):
    return min(routes, key=lambda r: haversine_km(r["origin_lat"], r["origin_lon"], *a)
               + haversine_km(r["dest_lat"], r["dest_lon"], *b))


def cache_rows(routes, cells, model, ratio):
    hubs = list(HUBS.items())[:CACHE_HUBS]
    rng = random.Random(SEED)
    trips = []
    for _ in range(CACHE_TRIPS):
        (_, (a, _)), (_, (b, _)) = rng.sample(hubs, 2)
        trips.append((a, b))

    picked, lookups, mismatch = {}, {"current_points_2dp": [], "current_points_cell": [], "proposed_M2_cell": []}, []
    for a, b in trips:
        if (a, b) not in picked:
            r = nearest_route(routes, a, b)
            mismatch.append(haversine_km(r["origin_lat"], r["origin_lon"], *a) + haversine_km(r["dest_lat"], r["dest_lon"], *b))
            picked[(a, b)] = (r, current_points(r), proposed_cells(r, model, ratio))
        r, pts, chosen = picked[(a, b)]
        lookups["current_points_2dp"].append([(round(p[0], KEY_DECIMALS), round(p[1], KEY_DECIMALS)) for p in pts])
        lookups["current_points_cell"].append([nearest_cell(p[0], p[1], cells) for p in pts])
        lookups["proposed_M2_cell"].append(list(chosen))

    rows = []
    for scheme, per_trip in lookups.items():
        seen, hits, total = set(), 0, 0
        for keys in per_trip:
            for key in keys:
                total += 1
                hits += key in seen
                seen.add(key)
        rows.append({"key_scheme": scheme, "trips": len(per_trip), "ttl_min": CACHE_TTL_MIN, "lookups": total,
                     "unique_keys": len(seen), "hits": hits, "hit_rate": round(hits / total, 4),
                     "api_calls": total - hits})
    return rows, len(picked), float(np.mean(mismatch))


def write(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out-dir", default=OUT_DIR)
    a = p.parse_args()
    cells, model = load_cells(), load_model()
    ratio = load_constants()["servingBudgetRatio"]

    calls = call_rows(load("routes_holdout.parquet"), cells, ratio)
    write(os.path.join(a.out_dir, "T3_calls.csv"), calls)
    cache, pairs, mismatch = cache_rows(load("routes.parquet"), cells, model, ratio)
    write(os.path.join(a.out_dir, "T3_cache.csv"), cache)

    for row in calls + cache:
        print(row)
    print(f"cache trips use {pairs} hub pairs; mean origin+dest gap to the reused route {mismatch:.2f} km")


if __name__ == "__main__":
    main()
