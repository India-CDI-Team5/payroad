"""Download the hourly precipitation history of every weather cell in the collection area.

Each cell is fetched once per period, so (route, departure time) samples can later be cut
offline without further API calls. The history is split into PERIODS so it can be extended
(e.g. more monsoon seasons) without re-downloading what is already on disk. One cell per
request, paced under Open-Meteo's hourly limit (a 1-year request counts as ~26 calls).
Finished cells are kept in data/cells_raw/<period>/, so an interrupted run resumes.

Run from PartB/ (after training.meteo_probe):  python -m training.collect_groundtruth
Writes data/cells.parquet: one row per cell with its UTC hourly series over all periods.
"""
import json
import os
import time
from datetime import date, datetime, timedelta

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from clients.meteo_client import api_calls, fetch_archive

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
RAW_DIR = os.path.join(DATA_DIR, "cells_raw")
VARIABLES = "precipitation,rain,weather_code"
# Four south-west monsoons (Jun-Sep) and retreating monsoons (Oct-Nov), with the dry
# seasons between them as the no-rain control.
PERIODS = [(date(2022, 6, 1), date(2024, 5, 31)), (date(2024, 6, 1), date(2025, 11, 30))]
MAX_CALLS_PER_HOUR = 4000        # headroom under the 5,000/hour limit
MAX_CALLS_PER_MIN = 450          # headroom under the 600/min limit


def period_tag(start, end):
    return f"{start.isoformat()}_{end.isoformat()}"


def download(client, cells, start, end):
    folder = os.path.join(RAW_DIR, period_tag(start, end))
    os.makedirs(folder, exist_ok=True)
    per_cell = api_calls(1, (end - start).days + 1, len(VARIABLES.split(",")))
    pause = max(60 * per_cell / MAX_CALLS_PER_MIN, 3600 * per_cell / MAX_CALLS_PER_HOUR)
    fetched = 0
    for i, (lat, lon) in enumerate(cells):
        path = os.path.join(folder, f"{i:03d}.json")
        if os.path.exists(path):
            continue
        data = fetch_archive(client, [(lat, lon)], start, end, hourly=VARIABLES, retries=5)[0]
        if (data["latitude"], data["longitude"]) != (lat, lon):
            raise RuntimeError(f"cell {i}: asked {lat},{lon} but got {data['latitude']},{data['longitude']}")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        fetched += 1
        print(f"{period_tag(start, end)} cell {i + 1}/{len(cells)} done", flush=True)
        time.sleep(pause)
    return fetched, fetched * per_cell


def load_series(cells):
    """Concatenate every period in time order and check the hours are contiguous."""
    rows = []
    for i, (lat, lon) in enumerate(cells):
        series = {"time_utc": [], "precipitation_mm": [], "rain_mm": [], "weather_code": []}
        for start, end in sorted(PERIODS):
            with open(os.path.join(RAW_DIR, period_tag(start, end), f"{i:03d}.json"), encoding="utf-8") as f:
                h = json.load(f)["hourly"]
            series["time_utc"] += h["time"]
            series["precipitation_mm"] += h["precipitation"]
            series["rain_mm"] += h["rain"]
            series["weather_code"] += h["weather_code"]
        t = series["time_utc"]
        first, last = datetime.fromisoformat(t[0]), datetime.fromisoformat(t[-1])
        if len(t) != int((last - first) / timedelta(hours=1)) + 1:
            raise RuntimeError(f"cell {i}: hourly series has gaps or overlaps")
        rows.append({"cell": i, "lat": lat, "lon": lon, **series})
    return rows


def main():
    with open(os.path.join(DATA_DIR, "grid_cells.json"), encoding="utf-8") as f:
        cells = [tuple(c) for c in json.load(f)["cells"]]

    fetched, calls = 0, 0.0
    with httpx.Client(timeout=180) as client:
        for start, end in PERIODS:
            n, c = download(client, cells, start, end)
            fetched, calls = fetched + n, calls + c

    rows = load_series(cells)
    pq.write_table(pa.Table.from_pylist(rows), os.path.join(DATA_DIR, "cells.parquet"))

    hours = len(rows[0]["time_utc"])
    missing = sum(v is None for r in rows for v in r["precipitation_mm"])
    wet = sum(v is not None and v > 0.1 for r in rows for v in r["precipitation_mm"])
    summary = {"cells": len(rows), "hours_per_cell": hours,
               "periods": [period_tag(s, e) for s, e in sorted(PERIODS)],
               "cell_requests_this_run": fetched, "calls_this_run_estimate": round(calls, 1),
               "missing_values": missing, "wet_hour_share": round(wet / (len(rows) * hours), 4)}
    with open(os.path.join(DATA_DIR, "cells_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
