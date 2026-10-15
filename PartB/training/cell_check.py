"""Does the API pick the cell we assign? (2026-10-16, external review)

The paper groups route points by the nearest grid-cell centre (geo.nearest_cell over data/grid_cells.json) and
assumes one query of that cell reveals every point in it. Open-Meteo's default cell_selection is "land" (a land
cell with similar elevation, not necessarily the nearest). This sends a random sample of route points to the
forecast and archive endpoints (models=ecmwf_ifs, default cell_selection, and cell_selection=nearest for the
forecast) and counts how often the returned grid-cell centre equals the assigned cell.

Run from PartB/ (Docker, parquet):  python -m training.cell_check
Writes results/cell_check/summary.json.
"""
import datetime
import json
import os
import time

import httpx
import numpy as np

from clients.meteo_client import ARCHIVE_URL, FORECAST_URL, MODEL
from geo import nearest_cell
from training import final_eval
from weather import data

N_POINTS = 600
BATCH = 50
PAUSE_SEC = 12             # stay under the per-minute limit (each location may count as a call)
SEED = 20261016
OUT = os.path.join(final_eval.ROOT, "results", "cell_check")


def returned_centres(client, url, pts, extra):
    out = []
    for i in range(0, len(pts), BATCH):
        chunk = pts[i:i + BATCH]
        params = {"latitude": ",".join(f"{p[0]:.5f}" for p in chunk),
                  "longitude": ",".join(f"{p[1]:.5f}" for p in chunk),
                  "hourly": "precipitation", "models": MODEL, "timezone": "UTC", **extra}
        for attempt in range(6):
            r = client.get(url, params=params)
            if r.status_code != 429:
                break
            time.sleep(60 * (attempt + 1))
        r.raise_for_status()
        time.sleep(PAUSE_SEC)
        js = r.json()
        js = js if isinstance(js, list) else [js]
        out += [(d["latitude"], d["longitude"]) for d in js]
    return out


def main():
    with open(os.path.join(data.DATA_DIR, "grid_cells.json"), encoding="utf-8") as f:
        cells = [tuple(c) for c in json.load(f)["cells"]]
    import pyarrow.parquet as pq
    pts, used = [], []                      # route points and the cell the experiments assigned them
    for name in data.ROUTE_FILES.values():
        t = pq.read_table(os.path.join(data.DATA_DIR, name), columns=["lat", "lon", "cell"])
        for lats, lons, cs in zip(*(t.column(c).to_pylist() for c in ("lat", "lon", "cell"))):
            pts += list(zip(lats, lons))
            used += list(cs)
    rng = np.random.default_rng(SEED)
    idx = rng.choice(len(pts), size=min(N_POINTS, len(pts)), replace=False)
    pick = [pts[i] for i in idx]
    assigned = [cells[used[i]] for i in idx]
    summary_nearest = float(np.mean([cells[nearest_cell(la, lo, cells)] == a for (la, lo), a in zip(pick, assigned)]))

    today = datetime.date.today()
    jobs = {
        "forecast_default": (FORECAST_URL, {"forecast_days": 1}),
        "forecast_nearest": (FORECAST_URL, {"forecast_days": 1, "cell_selection": "nearest"}),
        "archive_default": (ARCHIVE_URL, {"start_date": (today - datetime.timedelta(days=30)).isoformat(),
                                          "end_date": (today - datetime.timedelta(days=30)).isoformat()}),
    }
    summary = {"n_points": len(pick), "n_route_points": len(pts), "stored_cell_equals_nearest": summary_nearest}
    with httpx.Client(timeout=120) as client:
        for name, (url, extra) in jobs.items():
            got = returned_centres(client, url, pick, extra)
            same = [abs(g[0] - a[0]) < 1e-3 and abs(g[1] - a[1]) < 1e-3 for g, a in zip(got, assigned)]
            known = [any(abs(g[0] - c[0]) < 1e-3 and abs(g[1] - c[1]) < 1e-3 for c in cells) for g in got]
            summary[name] = {"match_rate": float(np.mean(same)), "returned_in_grid_cells": float(np.mean(known))}
            print(name, summary[name], flush=True)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
