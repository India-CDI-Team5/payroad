"""Second-city replication of the shared spatial GP with exactly matched calls, pre-registered in
docs/shared-gp-city.md (committed before any weather of the new city was downloaded).

Steps (run from PartB/, Docker; `routes` needs ORS_API_KEY in ../.env):
    python -m training.city_replication grid      # cell centres of the new city (no weather values used)
    python -m training.city_replication routes    # ORS routes, resumable across days via the ORS disk cache
    python -m training.city_replication weather   # hourly precipitation of every cell (after the prereg commit)
    python -m training.city_replication run       # the experiment, once -> results/shared_gp_city/
    python -m training.city_replication smoke     # the run's code on Bengaluru validation hours only

Methods are those of training.shared_gp (G shared GP with Bengaluru's train-fitted hyperparameters, N non-GP
neighbour rule, P point-centre + cache, F full cache). Nothing is tuned on the new city. Calls are matched exactly:
each method's MAE at the target (0.5 x F's calls per trip) is that of a mixture of its two settings whose calls
bracket the target, so every method spends the target on average. Every method is treated alike: its rule shape is
fixed from Bengaluru (G's hyperparameters, N's radius 19 km), and on the new city only its one call knob (G tau,
N d, P rho) is placed, by calls alone; no method's settings are chosen by the new city's errors.
"""
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

import httpx
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from clients.meteo_client import fetch_archive
from geo import nearest_cell, offset
from training import collect_groundtruth as cg
from training import final_eval
from training import route_generator as rg
from training import shared_gp as sg
from weather import data
from weather.stats import holm, week_bootstrap_ci, wilcoxon_pair

CITY = "Hyderabad"
CENTER = (17.3850, 78.4867)
BBOX = {"lat_min": 17.085, "lat_max": 17.685, "lon_min": 78.187, "lon_max": 78.787}   # Bengaluru's 0.6 x 0.6 deg
HUBS = {                                       # name: ((lat, lon), weight), the Bengaluru pattern of 3/2/1 weights
    "HITEC City": ((17.4474, 78.3762), 3),
    "Secunderabad": ((17.4399, 78.4983), 3),
    "Banjara Hills": ((17.4126, 78.4482), 2),
    "Ameerpet": ((17.4375, 78.4483), 2),
    "Gachibowli": ((17.4401, 78.3489), 2),
    "Charminar": ((17.3616, 78.4747), 2),
    "Kukatpally": ((17.4849, 78.4138), 2),
    "Uppal": ((17.4058, 78.5591), 1),
    "LB Nagar": ((17.3457, 78.5522), 1),
    "Rajiv Gandhi Airport": ((17.2403, 78.4294), 1),
}
N_ROUTES = 150
ROUTE_SEED = 2028
PERIOD = (date(2024, 6, 1), date(2025, 11, 30))     # two south-west monsoons, as Bengaluru's second period
DIR = os.path.join(data.DATA_DIR, "hyderabad")
OUT = os.path.join(final_eval.ROOT, "results", "shared_gp_city")
N_PRIMARY, FRAC_PRIMARY = 20, 0.5
DESCRIPTIVE = ((20, 0.25), (20, 0.75), (5, 0.5), (10, 0.5), (50, 0.5))
TRANSFER = {"G": 0.09, "N": (19.0, 0.2), "P": 0.25}       # shared_gp's validation choice (results/shared_gp)
N_RADIUS = TRANSFER["N"][0]                                # N's rule shape, fixed from Bengaluru validation
WINDOWS = 300
SEED = 20261018
ALPHA = 0.05


def in_box(lat, lon):
    return BBOX["lat_min"] <= lat <= BBOX["lat_max"] and BBOX["lon_min"] <= lon <= BBOX["lon_max"]


# ---------- grid ----------
def cmd_grid():
    pts, lat = [], BBOX["lat_min"]
    while lat <= BBOX["lat_max"] + 1e-9:
        lon = BBOX["lon_min"]
        while lon <= BBOX["lon_max"] + 1e-9:
            pts.append((round(lat, 4), round(lon, 4)))
            lon += 0.04
        lat += 0.04
    day = date(2025, 8, 1)
    centres = set()
    with httpx.Client(timeout=60) as client:
        for i in range(0, len(pts), 100):
            for d in fetch_archive(client, pts[i:i + 100], day, day):      # only the snapped coordinates are kept
                centres.add((d["latitude"], d["longitude"]))
            time.sleep(0.3)
        cells = sorted(centres)
        rng = random.Random(7)
        probe = [(rng.uniform(BBOX["lat_min"], BBOX["lat_max"]), rng.uniform(BBOX["lon_min"], BBOX["lon_max"]))
                 for _ in range(60)]
        got = fetch_archive(client, probe, day, day)
    hits = sum(cells[nearest_cell(p[0], p[1], cells)] == (d["latitude"], d["longitude"]) for p, d in zip(probe, got))
    os.makedirs(DIR, exist_ok=True)
    with open(os.path.join(DIR, "grid_cells.json"), "w", encoding="utf-8") as f:
        json.dump({"city": CITY, "bbox": BBOX, "model": "ecmwf_ifs", "cells": cells,
                   "lattice_points": len(pts), "nearest_centre_check": [hits, len(probe)]}, f)
    print(f"{len(cells)} cells from {len(pts)} lattice points; nearest-centre check {hits}/{len(probe)}")


def load_cells():
    with open(os.path.join(DIR, "grid_cells.json"), encoding="utf-8") as f:
        return [tuple(c) for c in json.load(f)["cells"]]


# ---------- routes ----------
def candidate(rnd, stratum):
    lo, hi = rg.STRATA[stratum]
    names = list(HUBS)
    hub = rnd.choices(names, weights=[HUBS[n][1] for n in names])[0]
    o = offset(*HUBS[hub][0], abs(rnd.gauss(0, rg.ORIGIN_JITTER_KM)), rnd.uniform(0, 360))
    d = offset(*o, rnd.uniform(lo, hi) / rg.DETOUR, rnd.uniform(0, 360))
    return (hub, o, d) if in_box(*o) and in_box(*d) else None


def cmd_routes(reserve=5):
    cells = load_cells()
    rnd = random.Random(ROUTE_SEED)
    quota = {s: N_ROUTES // len(rg.STRATA) + (i < N_ROUTES % len(rg.STRATA)) for i, s in enumerate(rg.STRATA)}
    got, records, stats, stopped = Counter(), [], Counter(), None
    with httpx.Client(timeout=30) as client:
        ors = rg.Ors(client, reserve)
        while not stopped and any(got[s] < quota[s] for s in rg.STRATA):
            for stratum in [s for s in rg.STRATA if got[s] < quota[s]]:
                while True:
                    cand = candidate(rnd, stratum)
                    if cand is None:
                        stats["off_map"] += 1
                        continue
                    hub, o, d = cand
                    try:
                        res = ors.route(o, d)
                    except rg.QuotaExhausted as e:
                        stopped = f"ORS quota: {e.args[0]} left"
                        break
                    stats["ors_requests"] += 1
                    if "error" in res:
                        stats["unroutable"] += 1
                        continue
                    km = res["features"][0]["properties"]["summary"]["distance"] / 1000
                    lo, hi = rg.STRATA[stratum]
                    if not lo <= km < hi:
                        stats["wrong_length"] += 1
                        continue
                    records.append(rg.build_record("hyderabad", len(records), stratum, hub, o, d, res, cells))
                    got[stratum] += 1
                    break
                if stopped:
                    break
    summary = {"routes": len(records), "by_stratum": dict(got), **stats, "ors_calls_now": ors.calls,
               "ors_remaining": ors.remaining, "stopped": stopped,
               "share_U_ge_3": round(np.mean([r["unique_cells"] >= 3 for r in records]), 3) if records else None}
    if stopped:
        print(json.dumps(summary), "\nre-run tomorrow: cached ORS answers replay call-free")
        return 1
    pq.write_table(pa.Table.from_pylist(records), os.path.join(DIR, "routes.parquet"))
    with open(os.path.join(DIR, "routes_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary))
    return 0


def load_routes():
    out = []
    for r in pq.read_table(os.path.join(DIR, "routes.parquet")).to_pylist():
        out.append({"cell": np.array(r["cell"], dtype=np.int64), "s_km": np.array(r["s_km"], dtype=np.float64),
                    "t_min": np.array(r["t_min"], dtype=np.float64), "distance_km": r["distance_km"],
                    "unique_cells": r["unique_cells"], "stratum": r["stratum"]})
    return out


# ---------- weather ----------
def cmd_weather():
    cells = load_cells()
    cg.RAW_DIR = os.path.join(DIR, "cells_raw")                     # cg.download reads it at call time
    with httpx.Client(timeout=180) as client:
        n, calls = cg.download(client, cells, *PERIOD)
    print(f"{n} cells fetched now (~{calls:.0f} API calls)")


def load_weather(n_cells):
    folder = os.path.join(DIR, "cells_raw", cg.period_tag(*PERIOD))
    series, first = [], None
    for i in range(n_cells):
        with open(os.path.join(folder, f"{i:03d}.json"), encoding="utf-8") as f:
            h = json.load(f)["hourly"]
        t0, t1 = datetime.fromisoformat(h["time"][0]), datetime.fromisoformat(h["time"][-1])
        if len(h["time"]) != int((t1 - t0) / timedelta(hours=1)) + 1 or (first is not None and t0 != first):
            raise RuntimeError(f"cell {i}: series gaps or misaligned start")
        first = t0
        series.append([np.nan if v is None else float(v) for v in h["precipitation"]])
    times = np.datetime64(first, "m") + np.arange(len(series[0])) * np.timedelta64(60, "m")
    return times, np.array(series)


def city_xy(cells):
    lat, lon = np.array([c[0] for c in cells]), np.array([c[1] for c in cells])
    lat0 = lat.mean()
    return np.column_stack([(lon - lon.mean()) * 111.32 * np.cos(np.radians(lat0)), (lat - lat0) * 110.57])


# ---------- matched-calls comparison ----------
def settings():
    return {"G": [("G", t) for t in sg.TAUS] + [("F", None)],
            "N": [("N", (N_RADIUS, d)) for d in sg.DRANGE] + [("F", None)],
            "P": [("P", p) for p in sg.PRHOS] + [("F", None)]}


def per_window_err(st):
    keep = st[:, 3] > 0
    e = np.full(len(st), np.nan)
    e[keep] = st[keep, 2] / st[keep, 3]
    return e


def matched(fam, runs, target):
    """Mixture of the two settings whose calls bracket target: (calls, mae, per-window error, info).
    Settings are ordered by calls alone (ties: by the setting's text, never by error) for every method."""
    pts = sorted((sg.calls_mae(st) + (key,) for key, st in runs.items()), key=lambda x: (x[0], str(x[2])))
    if target <= pts[0][0]:
        a = b = pts[0]
        w = 1.0
    else:
        i = next((i for i in range(1, len(pts)) if pts[i][0] >= target), len(pts) - 1)
        a, b = pts[i - 1], pts[i]
        w = 1.0 if b[0] == a[0] else (b[0] - target) / (b[0] - a[0])      # weight on a
    ea, eb = per_window_err(runs[a[2]]), per_window_err(runs[b[2]])
    info = {"a": str(a[2]), "b": str(b[2]), "w_a": w, "cannot_reach": bool(target < pts[0][0])}
    return w * a[0] + (1 - w) * b[0], w * a[1] + (1 - w) * b[1], w * ea + (1 - w) * eb, info


def test(eg, eo, windows):
    keep = ~np.isnan(eg) & ~np.isnan(eo)
    by = defaultdict(list)
    for w, d in zip([w for w, k in zip(windows, keep) if k], (eg - eo)[keep]):
        by[w["week"]].append(d)
    mean, lo, hi = week_bootstrap_ci(by, B=sg.BOOT_B, seed=sg.BOOT_SEED)
    _, med, p = wilcoxon_pair(eg[keep], eo[keep])
    return {"windows": int(keep.sum()), "mean_diff": mean, "ci_lo": lo, "ci_hi": hi, "median_diff": med, "p": p}


def evaluate(times, precip, xy, routes, out_dir, log, n_windows=WINDOWS, taus=None, keep_week=lambda wk: True):
    if taus is not None:
        sg.TAUS = taus
    model, _ = final_eval.load_models()
    ctx = {"xy": xy, "model": model, "kr": sg.Kriger(xy), "precip": precip}
    hours = sg.wet_hours(times, precip, keep_week)
    sg.WINDOWS = n_windows
    summary = {"city": CITY, "git_head": (final_eval.git("rev-parse", "HEAD") or "").strip() or None,
               "cells": len(xy), "routes": len(routes),
               "share_U_ge_3": float(np.mean([r["unique_cells"] >= 3 for r in routes])),
               "wet_hours": len(hours), "spatial": sg.SPATIAL, "runs": {}, "tests": []}
    for N in sorted({N_PRIMARY} | {n for n, _ in DESCRIPTIVE}):
        wins = sg.make_windows(times, precip, hours, routes, N, np.random.default_rng([SEED, N]))
        fracs = sorted({f for n, f in ((N_PRIMARY, FRAC_PRIMARY),) + DESCRIPTIVE if n == N})
        runs = {(m, p): sg.run_windows(m, p, wins, ctx) for m, p in {s for v in settings().values() for s in v}}
        full = sg.calls_mae(runs[("F", None)])[0]
        for frac in fracs:
            target = frac * full
            res = {f: matched(f, {k: runs[k] for k in settings()[f]}, target) for f in ("G", "N", "P")}
            row = {"N": N, "frac": frac, "full_calls": full, "target": target,
                   **{f: {"calls": c, "mae": m, **info} for f, (c, m, _, info) in res.items()}}
            if frac == FRAC_PRIMARY:
                row["transfer"] = {f: dict(zip(("calls", "mae"), sg.calls_mae(
                    runs.get((f, TRANSFER[f])) if (f, TRANSFER[f]) in runs else sg.run_windows(f, TRANSFER[f], wins, ctx))))
                                   for f in TRANSFER}
            summary["runs"][f"N{N}_f{frac}"] = row
            log(f"N={N} frac={frac} target {target:.3f}: " + "  ".join(
                f"{f} calls {row[f]['calls']:.3f} MAE {row[f]['mae']:.4f}" for f in ("G", "N", "P")))
            if (N, frac) == (N_PRIMARY, FRAC_PRIMARY):
                for name, other in (("R1", "N"), ("R2", "P")):
                    summary["tests"].append({"test": name, "vs": other, "G_calls": row["G"]["calls"],
                                             f"{other}_calls": row[other]["calls"], "G_mae": row["G"]["mae"],
                                             f"{other}_mae": row[other]["mae"],
                                             **test(res["G"][2], res[other][2], wins)})
    for t, adj in zip(summary["tests"], holm([t["p"] for t in summary["tests"]])):
        t["p_holm"] = adj
        t["passed"] = bool(adj < ALPHA and t["mean_diff"] < 0)
    summary["all_passed"] = all(t["passed"] for t in summary["tests"])
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=2, default=float)
        f.write("\n")
    for t in summary["tests"]:
        log(f'{t["test"]} G vs {t["vs"]}: MAE {t["G_mae"]:.4f} vs {t[t["vs"] + "_mae"]:.4f}, calls {t["G_calls"]:.3f} '
            f'vs {t[t["vs"] + "_calls"]:.3f}, mean diff {t["mean_diff"]:.4f} [{t["ci_lo"]:.4f}, {t["ci_hi"]:.4f}], '
            f'p_holm {t["p_holm"]:.3g} -> {"pass" if t["passed"] else "FAIL"}')
    log(f"ALL PASSED: {summary['all_passed']}")
    return 0


def cmd_run():
    cells = load_cells()
    times, precip = load_weather(len(cells))
    return evaluate(times, precip, city_xy(cells), load_routes(), OUT, lambda m: print(m, flush=True))


def cmd_smoke():
    """Bengaluru validation hours and routes, 3 windows, coarse tau grid: checks the code, sees no new-city weather."""
    times, precip = sg.main_period()
    split_of = sg.week_split()
    routes = [r for k, r in sorted(data.load_routes().items()) if k[0] == "main"]
    return evaluate(times, precip, sg.cell_xy(), routes, os.path.join(OUT, "smoke"), lambda m: print(m, flush=True),
                    n_windows=3, taus=sg.TAUS[::10], keep_week=lambda wk: split_of.get(wk) == "val")


if __name__ == "__main__":
    sys.exit({"grid": cmd_grid, "routes": cmd_routes, "weather": cmd_weather, "run": cmd_run,
              "smoke": cmd_smoke}[sys.argv[1]]() or 0)
