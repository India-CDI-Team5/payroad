"""Measure what the Model A collection plan depends on, before collecting anything.

1. How far back (and up to when) Archive `models=ecmwf_ifs` has data.
2. Whether `best_match` returns the same values as `ecmwf_ifs` here.
3. The grid-cell centres covering the collection area, and whether "nearest centre"
   reproduces the cell Open-Meteo actually picks (so routes can be mapped offline).
4. How often it rains in the planned period, and the API-call budget for the collection.

Run from PartB/:  python -m training.meteo_probe
Writes data/grid_cells.json and data/probe_report.json.
"""
import json
import math
import os
import random
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from training.geo import BBOX, nearest_cell

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
MODEL = "ecmwf_ifs"
CENTER = (12.9716, 77.5946)
LATTICE_STEP_DEG = 0.04          # finer than the ~0.07 x 0.082 deg cell, so every cell is hit
CHUNK = 100                      # locations per request
PLAN_START, PLAN_END = date(2022, 6, 1), date(2025, 11, 30)
RAIN_MM = 0.1
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# Open-Meteo counting rule (open-meteo.com/en/pricing): >10 variables or >2 weeks per location
# count fractionally more. Multi-location weighting is not documented, so each location is
# counted as its own call (conservative).
calls_used = 0.0


def weight(n_locations, days, n_vars=1):
    return n_locations * max(1.0, days / 14) * max(1.0, n_vars / 10)


def archive(client, points, start, end, model=MODEL, variables="precipitation"):
    global calls_used
    days = (end - start).days + 1
    params = {
        "latitude": ",".join(f"{p[0]:.5f}" for p in points),
        "longitude": ",".join(f"{p[1]:.5f}" for p in points),
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "hourly": variables, "timezone": "UTC",
    }
    if model:
        params["models"] = model
    r = client.get(ARCHIVE_URL, params=params)
    if r.status_code != 200:
        raise RuntimeError(f"Open-Meteo {r.status_code}: {r.text[:200]}")
    calls_used += weight(len(points), days, len(variables.split(",")))
    time.sleep(0.3)
    data = r.json()
    return data if isinstance(data, list) else [data]


def availability(client):
    first = archive(client, [CENTER], date(2016, 12, 25), date(2017, 1, 7))[0]["hourly"]
    first_ts = next((t for t, v in zip(first["time"], first["precipitation"]) if v is not None), None)
    today = datetime.now(timezone.utc).date() - timedelta(days=1)  # archive dates are UTC days
    recent = archive(client, [CENTER], today - timedelta(days=10), today)[0]["hourly"]
    last_ts = next((t for t, v in reversed(list(zip(recent["time"], recent["precipitation"]))) if v is not None), None)
    return {"first_hour": first_ts, "last_hour": last_ts}


def best_match_equal(client):
    pts = [CENTER, (13.1986, 77.7066), (12.8452, 77.6602)]
    s, e = date(2025, 8, 1), date(2025, 8, 14)
    a = archive(client, pts, s, e, model=MODEL)
    b = archive(client, pts, s, e, model=None)
    same = total = 0
    for x, y in zip(a, b):
        for u, v in zip(x["hourly"]["precipitation"], y["hourly"]["precipitation"]):
            total += 1
            same += (u == v)
    return {"hours_compared": total, "identical_share": round(same / total, 4),
            "same_cell": all((x["latitude"], x["longitude"]) == (y["latitude"], y["longitude"]) for x, y in zip(a, b))}


def lattice():
    pts, lat = [], BBOX["lat_min"]
    while lat <= BBOX["lat_max"] + 1e-9:
        lon = BBOX["lon_min"]
        while lon <= BBOX["lon_max"] + 1e-9:
            pts.append((round(lat, 4), round(lon, 4)))
            lon += LATTICE_STEP_DEG
        lat += LATTICE_STEP_DEG
    return pts


def grid_cells(client):
    day = date(2025, 8, 1)
    centres = set()
    pts = lattice()
    for i in range(0, len(pts), CHUNK):
        for d in archive(client, pts[i:i + CHUNK], day, day):
            centres.add((d["latitude"], d["longitude"]))
    return sorted(centres), len(pts)


def mapping_check(client, cells, n=60, seed=7):
    rng = random.Random(seed)
    pts = [(rng.uniform(BBOX["lat_min"], BBOX["lat_max"]), rng.uniform(BBOX["lon_min"], BBOX["lon_max"])) for _ in range(n)]
    got = archive(client, pts, date(2025, 8, 1), date(2025, 8, 1))
    hits = sum(cells[nearest_cell(p[0], p[1], cells)] == (d["latitude"], d["longitude"]) for p, d in zip(pts, got))
    return {"points": n, "nearest_centre_matches": hits, "accuracy": round(hits / n, 3)}


def rain_share(client, cells):
    # Three cells spread across the area, whole planned period.
    picks = [cells[0], cells[len(cells) // 2], cells[-1]]
    series = archive(client, picks, PLAN_START, PLAN_END)
    wet = total = 0
    monthly = {}
    for s in series:
        for t, v in zip(s["hourly"]["time"], s["hourly"]["precipitation"]):
            if v is None:
                continue
            total += 1
            m = t[:7]
            monthly.setdefault(m, [0, 0])
            monthly[m][1] += 1
            if v > RAIN_MM:
                wet += 1
                monthly[m][0] += 1
    return {"threshold_mm": RAIN_MM, "wet_hour_share": round(wet / total, 4),
            "wet_hour_share_by_month": {m: round(w / n, 3) for m, (w, n) in sorted(monthly.items())}}


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    report = {"model": MODEL, "bbox": BBOX}
    with httpx.Client(timeout=60) as client:
        report["availability"] = availability(client)
        report["best_match_vs_model"] = best_match_equal(client)
        cells, n_lattice = grid_cells(client)
        report["grid"] = {"lattice_points": n_lattice, "unique_cells": len(cells)}
        report["mapping_check"] = mapping_check(client, cells)
        report["rain"] = rain_share(client, cells)

    days = (PLAN_END - PLAN_START).days + 1
    per_cell = weight(1, days)
    report["collection_budget"] = {
        "period": [PLAN_START.isoformat(), PLAN_END.isoformat()], "days": days,
        "calls_per_cell": round(per_cell, 1), "cells": len(cells),
        "total_calls": math.ceil(per_cell * len(cells)),
        "limits": {"per_minute": 600, "per_hour": 5000, "per_day": 10000},
        "min_hours_at_hourly_limit": round(per_cell * len(cells) / 5000, 2),
    }
    report["probe_calls_used_estimate"] = round(calls_used, 1)

    with open(os.path.join(DATA_DIR, "grid_cells.json"), "w", encoding="utf-8") as f:
        json.dump({"model": MODEL, "cells": cells}, f)
    with open(os.path.join(DATA_DIR, "probe_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
