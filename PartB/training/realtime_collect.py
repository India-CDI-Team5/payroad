"""Prospective real-time forecast collection, pre-registered in docs/realtime-check.md.

One run = one snapshot of what the base-fare service would receive right now: the Open-Meteo Forecast API,
models=ecmwf_ifs (the service's MODEL), hourly precipitation, forecast_days=2 (as the service), UTC, for all 82 Bengaluru grid
cells in one multi-coordinate request (82 calls). Every returned coordinate is checked against grid_cells.json
(within 0.01 deg). The raw JSON is written to data/realtime/<UTC stamp>.json together with the fetch time;
nothing is evaluated here. Meant to run hourly from Windows Task Scheduler; a failed run logs and exits non-zero.

    python PartB/training/realtime_collect.py          # native Python is enough (json + httpx)
"""
import datetime
import json
import os
import sys
import time

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, "..", "data"))
OUT_DIR = os.path.join(DATA, "realtime")
LOG = os.path.join(OUT_DIR, "collect.log")
URL = "https://api.open-meteo.com/v1/forecast"
MODEL = "ecmwf_ifs"                 # = clients.meteo_client.MODEL (not imported, to keep this script standalone)
TOLERANCE_DEG = 0.01
RETRIES, BACKOFF_SEC = 3, 60


def log(msg):
    os.makedirs(OUT_DIR, exist_ok=True)
    line = f"{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%dT%H:%M:%SZ} {msg}"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def fetch(cells):
    params = {"latitude": ",".join(f"{c[0]:.5f}" for c in cells),
              "longitude": ",".join(f"{c[1]:.5f}" for c in cells),
              "hourly": "precipitation", "forecast_days": 2, "timezone": "UTC", "models": MODEL}
    for attempt in range(RETRIES + 1):
        try:
            r = httpx.get(URL, params=params, timeout=60)
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, list) else [data]
            err = f"HTTP {r.status_code}: {r.text[:200]}"
        except httpx.HTTPError as e:
            err = repr(e)
        if attempt < RETRIES:
            time.sleep(BACKOFF_SEC * (attempt + 1))
    raise RuntimeError(err)


def main():
    with open(os.path.join(DATA, "grid_cells.json"), encoding="utf-8") as f:
        cells = [tuple(c) for c in json.load(f)["cells"]]
    fetched_at = datetime.datetime.now(datetime.timezone.utc)
    try:
        data = fetch(cells)
        if len(data) != len(cells):
            raise RuntimeError(f"{len(data)} locations returned for {len(cells)} cells")
        for i, (c, d) in enumerate(zip(cells, data)):
            if abs(d["latitude"] - c[0]) > TOLERANCE_DEG or abs(d["longitude"] - c[1]) > TOLERANCE_DEG:
                raise RuntimeError(f"cell {i}: asked {c} got {d['latitude']},{d['longitude']}")
    except Exception as e:  # noqa: BLE001 - one line in the log is the whole failure report
        log(f"FAIL {e}")
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{fetched_at:%Y%m%dT%H%MZ}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"fetched_at_utc": fetched_at.strftime("%Y-%m-%dT%H:%M:%SZ"), "model": MODEL,
                   "cells": cells, "hourly": [{"time": d["hourly"]["time"],
                                               "precipitation": d["hourly"]["precipitation"]} for d in data]}, f)
    wet = sum(1 for d in data if any((v or 0) > 0.1 for v in d["hourly"]["precipitation"]))
    log(f"ok {os.path.basename(path)} ({wet}/{len(cells)} cells with > 0.1 mm/h in the next day)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
