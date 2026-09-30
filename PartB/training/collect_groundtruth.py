"""Download the hourly precipitation history of every weather cell in the collection area.

Each cell is fetched once for the whole period, so (route, departure time) samples can later
be cut offline without further API calls. One cell per request, paced to stay under
Open-Meteo's 600 calls/min (a 548-day request counts as ~39 calls). Finished cells are kept
in data/cells_raw/, so an interrupted run resumes where it stopped.

Run from PartB/ (after training.meteo_probe):  python -m training.collect_groundtruth
Writes data/cells.parquet: one row per cell with its UTC hourly series.
"""
import json
import os
import time
from datetime import date

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from training.meteo_probe import ARCHIVE_URL, MODEL, PLAN_END, PLAN_START, weight

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
RAW_DIR = os.path.join(DATA_DIR, "cells_raw")
VARIABLES = "precipitation,rain,weather_code"
MAX_CALLS_PER_MIN = 450          # headroom under the 600/min limit


def fetch_cell(client, lat, lon):
    params = {"latitude": f"{lat:.5f}", "longitude": f"{lon:.5f}", "models": MODEL,
              "start_date": PLAN_START.isoformat(), "end_date": PLAN_END.isoformat(),
              "hourly": VARIABLES, "timezone": "UTC"}
    for attempt in range(5):
        r = client.get(ARCHIVE_URL, params=params)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(60 * (attempt + 1))
            continue
        raise RuntimeError(f"Open-Meteo {r.status_code}: {r.text[:200]}")
    raise RuntimeError("Open-Meteo kept rate-limiting; try again later")


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "grid_cells.json"), encoding="utf-8") as f:
        cells = [tuple(c) for c in json.load(f)["cells"]]
    days = (PLAN_END - PLAN_START).days + 1
    per_cell = weight(1, days, len(VARIABLES.split(",")))
    pause = 60 * per_cell / MAX_CALLS_PER_MIN

    fetched = 0
    with httpx.Client(timeout=120) as client:
        for i, (lat, lon) in enumerate(cells):
            path = os.path.join(RAW_DIR, f"{i:03d}.json")
            if os.path.exists(path):
                continue
            data = fetch_cell(client, lat, lon)
            if (data["latitude"], data["longitude"]) != (lat, lon):
                raise RuntimeError(f"cell {i}: asked {lat},{lon} but got {data['latitude']},{data['longitude']}")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            fetched += 1
            print(f"cell {i + 1}/{len(cells)} done", flush=True)
            time.sleep(pause)

    rows = []
    for i, (lat, lon) in enumerate(cells):
        with open(os.path.join(RAW_DIR, f"{i:03d}.json"), encoding="utf-8") as f:
            h = json.load(f)["hourly"]
        rows.append({"cell": i, "lat": lat, "lon": lon, "time_utc": h["time"],
                     "precipitation_mm": h["precipitation"], "rain_mm": h["rain"],
                     "weather_code": h["weather_code"]})
    pq.write_table(pa.Table.from_pylist(rows), os.path.join(DATA_DIR, "cells.parquet"))

    hours = len(rows[0]["time_utc"])
    missing = sum(v is None for r in rows for v in r["precipitation_mm"])
    wet = sum(v is not None and v > 0.1 for r in rows for v in r["precipitation_mm"])
    summary = {"cells": len(rows), "hours_per_cell": hours, "period": [PLAN_START.isoformat(), PLAN_END.isoformat()],
               "fetched_this_run": fetched, "calls_this_run_estimate": round(fetched * per_cell, 1),
               "missing_values": missing, "wet_hour_share": round(wet / (len(rows) * hours), 4)}
    with open(os.path.join(DATA_DIR, "cells_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
