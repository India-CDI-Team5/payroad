"""Time-axis check of ml-design v5 §5.3 (card B9): how often a day-ahead forecast flips the surcharge decision.

The base price is set from the forecast at departure; this measures what changes when the ground-truth
profile (ERA-style history of data/cells.parquet) is replaced by the forecast issued one day earlier.

Probe on 2026-10-11 (3 calls): previous-runs-api with models=ecmwf_ifs returns the right cell but every
value is null; without `models` (Open-Meteo best_match) it returns values on exactly the same cell
coordinate (12.970123, 77.56364), for 2024-06-01..03 and 2025-11-28..30. So this script asks without
`models` and checks every cell's returned coordinate against grid_cells.json (within 0.01°).

Run from PartB/:  python -m training.forecast_error
  1. downloads precipitation_previous_day1 for the 82 cells, 2024-06-01..2025-11-30, one cell per request,
     resumable (data/cells_forecast_d1_raw/), paced under 600 calls/min and 5,000/h;
  2. writes data/cells_forecast_d1.parquet with the columns of cells.parquet (rain_mm, weather_code null);
  3. writes ../results/model_a/forecast_error.csv.

Error is the day-ahead forecast route mean m_fc against the ground-truth route mean m on the same route and
departure, over test-split wet samples whose whole trip lies in the forecast period. 1-day-ahead error is
an upper bound for the service, whose lead time is 0-2 h (§5.3 step 4).
"""
import argparse
import csv
import gzip
import json
import os
import time
from datetime import date

import httpx
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from clients.meteo_client import api_calls
from pricing.base_price import beta, load_constants
from training.build_samples import arrival_values, load_cells
from weather.data import WET_MM, load_routes, load_samples

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "data")
RAW_DIR = os.path.join(DATA_DIR, "cells_forecast_d1_raw")
OUT_PARQUET = os.path.join(DATA_DIR, "cells_forecast_d1.parquet")
RESULTS = os.path.normpath(os.path.join(HERE, "..", "..", "results", "model_a"))
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
VARIABLE = "precipitation_previous_day1"
START, END = date(2024, 6, 1), date(2025, 11, 30)
MAX_CALLS_PER_HOUR = 4000        # headroom under 5,000/hour (same as collect_groundtruth)
MAX_CALLS_PER_MIN = 450          # headroom under 600/min
GRID_TOLERANCE_DEG = 0.01
COLUMNS = ["n", "mae_fc", "p90_abs_err", "flip_rate", "m1_mae_rho50"]


# ---------- download ----------

def fetch_cell(client, lat, lon, retries=5, backoff_sec=120):
    params = {"latitude": f"{lat:.5f}", "longitude": f"{lon:.5f}", "hourly": VARIABLE,
              "start_date": START.isoformat(), "end_date": END.isoformat(), "timezone": "UTC"}
    for attempt in range(retries + 1):
        r = client.get(PREVIOUS_RUNS_URL, params=params)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429 and attempt < retries:
            time.sleep(backoff_sec * (attempt + 1))
            continue
        raise RuntimeError(f"Open-Meteo {r.status_code}: {r.text[:200]}")


def download(client, cells):
    """One JSON per cell in RAW_DIR; cells already on disk are skipped. Returns (requests, call estimate)."""
    os.makedirs(RAW_DIR, exist_ok=True)
    per_cell = api_calls(1, (END - START).days + 1, 1)
    pause = max(60 * per_cell / MAX_CALLS_PER_MIN, 3600 * per_cell / MAX_CALLS_PER_HOUR)
    fetched = 0
    for i, (lat, lon) in enumerate(cells):
        path = os.path.join(RAW_DIR, f"{i:03d}.json")
        if os.path.exists(path):
            continue
        data = fetch_cell(client, lat, lon)
        if abs(data["latitude"] - lat) > GRID_TOLERANCE_DEG or abs(data["longitude"] - lon) > GRID_TOLERANCE_DEG:
            raise RuntimeError(f"cell {i}: asked {lat},{lon} but got {data['latitude']},{data['longitude']}")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        fetched += 1
        print(f"forecast d1 cell {i + 1}/{len(cells)} done", flush=True)
        if i < len(cells) - 1:
            time.sleep(pause)
    return fetched, fetched * per_cell


def write_parquet(cells, raw_dir=RAW_DIR, out=OUT_PARQUET):
    rows = []
    for i, (lat, lon) in enumerate(cells):
        with open(os.path.join(raw_dir, f"{i:03d}.json"), encoding="utf-8") as f:
            h = json.load(f)["hourly"]
        n = len(h["time"])
        rows.append({"cell": i, "lat": lat, "lon": lon, "time_utc": h["time"],
                     "precipitation_mm": h[VARIABLE], "rain_mm": [None] * n, "weather_code": [None] * n})
    schema = pa.schema([("cell", pa.int64()), ("lat", pa.float64()), ("lon", pa.float64()),
                        ("time_utc", pa.list_(pa.string())), ("precipitation_mm", pa.list_(pa.float64())),
                        ("rain_mm", pa.list_(pa.float64())), ("weather_code", pa.list_(pa.int64()))])
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), out)


# ---------- evaluation ----------

def surcharged(m, c):
    return beta(m, 0.0, c) > c["surchargeThreshold"]


def forecast_means(samples, routes, fc_times, fc_precip):
    """{sample_id: m_fc} for samples whose whole trip lies inside the forecast series; nan values drop a sample."""
    out = {}
    first = fc_times[0]
    last_hour = len(fc_times) - 1
    for s in samples:
        route = routes[(s["route_set"], s["route_id"])]
        offset = (np.datetime64(s["departure_utc"], "m") - first) / np.timedelta64(1, "h")
        if offset < 0 or offset + route["t_min"].max() / 60.0 + 1 > last_hour:
            continue
        values = arrival_values(fc_precip, route["cell"], route["t_min"], np.array([offset]))[0]
        if np.isnan(values).any():
            continue
        out[s["sample_id"]] = float(np.mean(values))
    return out


def m1_errors(per_sample_path, rho=0.5):
    """{sample_id: abs_err} of M1 at rho from test_per_sample.csv.gz."""
    out = {}
    with gzip.open(per_sample_path, "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            # k_abs rows (F1_kabs) leave rho blank
            if r["method"] == "M1" and r["rho"] != "" and float(r["rho"]) == rho and r["abs_err"] != "":
                out[int(r["sample_id"])] = float(r["abs_err"])
    return out


def evaluate(samples, routes, fc_times, fc_precip, m1_err, c):
    """One summary row over test wet samples in the forecast period, plus the counts behind it."""
    wet = [s for s in samples if s["split"] == "test" and np.max(s["gt_mm"]) > WET_MM]
    m_fc = forecast_means(wet, routes, fc_times, fc_precip)
    used = [s for s in wet if s["sample_id"] in m_fc]
    m = np.array([s["route_mean_mm"] for s in used])
    f = np.array([m_fc[s["sample_id"]] for s in used])
    err = np.abs(f - m)
    flips = np.array([surcharged(a, c) != surcharged(b, c) for a, b in zip(m, f)])
    m1 = [m1_err[s["sample_id"]] for s in used if s["sample_id"] in m1_err]
    row = {"n": len(used),
           "mae_fc": float(err.mean()) if len(used) else np.nan,
           "p90_abs_err": float(np.percentile(err, 90)) if len(used) else np.nan,
           "flip_rate": float(flips.mean()) if len(used) else np.nan,
           "m1_mae_rho50": float(np.mean(m1)) if m1 else np.nan}
    counts = {"test_wet": len(wet), "in_period": len(used), "with_m1": len(m1),
              "flips": int(flips.sum()), "true_surcharged": int(sum(surcharged(x, c) for x in m))}
    return row, counts


def write_csv(path, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(COLUMNS)
        w.writerow([row["n"]] + ["" if np.isnan(row[k]) else f"{row[k]:.6f}" for k in COLUMNS[1:]])


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--skip-download", action="store_true", help="use the JSON files already in the raw folder")
    p.add_argument("--results-dir", default=RESULTS)
    a = p.parse_args()
    with open(os.path.join(DATA_DIR, "grid_cells.json"), encoding="utf-8") as f:
        cells = [tuple(c) for c in json.load(f)["cells"]]

    fetched, calls = 0, 0.0
    if not a.skip_download:
        with httpx.Client(timeout=180) as client:
            fetched, calls = download(client, cells)
    write_parquet(cells)

    fc_times, fc_precip = load_cells(OUT_PARQUET)
    row, counts = evaluate(load_samples(["test"]), load_routes(), fc_times, fc_precip,
                           m1_errors(os.path.join(a.results_dir, "test_per_sample.csv.gz")), load_constants())
    write_csv(os.path.join(a.results_dir, "forecast_error.csv"), row)
    print(json.dumps({"cell_requests_this_run": fetched, "calls_this_run_estimate": round(calls, 1),
                      "missing_values": int(np.isnan(fc_precip).sum()), **counts, **row}, indent=2))


if __name__ == "__main__":
    main()
