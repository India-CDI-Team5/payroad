"""Real-forecast check, pre-registered in docs/forecast-check.md (committed before this was run on test weeks).

Same comparison as training.temporal_check, but the precipitation field is the issued day-ahead forecast
(data/cells_forecast_d1.parquet, Previous Runs API, 2024-06-01..2025-11-30) instead of the analysis data, and the
truth is that forecast's full query. Departures come from test-split ISO weeks only (IST 06-23 h, up to 4 wet ones
per U >= 3 route). Tests F-1 M2 - H-P and F-2 B1 - M2 at k/U = 0.5, two-sided Wilcoxon, Holm over the two,
supported if p_holm < 0.05 and the mean difference is positive. The previous system's point queries are described
without a test. Run once.

Run from PartB/ (Docker, parquet):
    python -m training.forecast_check            # -> results/forecast_check/
    python -m training.forecast_check --smoke    # val weeks, 20 samples, prints counts only
"""
import argparse
import csv
import datetime
import gzip
import hashlib
import json
import os
import sys
import time

import numpy as np

from training import final_eval
from training import temporal_check as tc
from training.build_samples import arrival_values, load_cells
from training.posthoc_extra import sample_count
from weather import data
from weather.methods import run
from weather.oracle import RouteOracle

PARQUET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "cells_forecast_d1.parquet")
SEED = 20261017
PER_ROUTE = 4
SAMPLE_ID_BASE = 950000
OUT_DIR = os.path.join(final_eval.ROOT, "results", "forecast_check")


def week_split():
    out = {}
    for s in data.load_samples(["train", "val", "test"]):
        out[data.iso_week(np.datetime64(s["departure_utc"], "m"))] = s["split"]
    return out


def candidate_offsets(times, split_of, keep):
    """Hour offsets (from times[0]) of every IST 06-23 h on the hour whose ISO week is in split `keep`."""
    local = times + data.IST
    hour = (local.astype("datetime64[h]") - local.astype("datetime64[D]")).astype(int)
    offsets, stamps = [], []
    for i, t in enumerate(times):
        if 6 <= hour[i] < 24 and split_of.get(data.iso_week(t)) == keep:
            offsets.append(float(i))
            stamps.append(t.astype("datetime64[m]").astype(datetime.datetime))
    return np.array(offsets), stamps


def draw_samples(routes, precip, offsets, stamps, rng):
    """Up to PER_ROUTE wet departures per U >= 3 route whose whole trip lies in the series."""
    samples, last = [], precip.shape[1] - 1
    for key in sorted(routes):
        route = routes[key]
        if route["unique_cells"] < 3:
            continue
        ok = offsets + route["t_min"].max() / 60.0 + 1 <= last
        values = arrival_values(precip, route["cell"], route["t_min"], offsets[ok])
        idx = np.nonzero(ok)[0]
        complete = ~np.isnan(values).any(axis=1)
        wet = idx[np.nonzero(complete & (np.nanmax(values, axis=1) > data.WET_MM))[0]]
        if len(wet) == 0:
            continue
        for d in np.sort(rng.choice(wet, size=min(PER_ROUTE, len(wet)), replace=False)):
            row = int(np.nonzero(idx == d)[0][0])
            samples.append({"route_set": key[0], "route_id": key[1], "departure_utc": stamps[d],
                            "gt_mm": values[row]})
    return samples


def make_cases(samples, routes):
    cases = []
    for i, smp in enumerate(samples):
        route = routes[(smp["route_set"], smp["route_id"])]
        year, week = data.iso_week(np.datetime64(smp["departure_utc"], "m"))
        cases.append({"sample": {**smp, "sample_id": SAMPLE_ID_BASE + i}, "route": route, "y": smp["gt_mm"],
                      "oracle": RouteOracle(route["cell"], smp["gt_mm"]), "s": route["s_km"], "t": route["t_min"],
                      "week": f"{year}-W{week:02d}"})
    return cases


def previous_rows(cases):
    """The previous system's queries (4/6/9/12 evenly spaced points, nearest value) on the same samples."""
    out = []
    for c in cases:
        n = min(sample_count(c["route"]["distance_km"]), len(c["s"]))
        r = run("B1", c["oracle"], c["s"], c["t"], n)
        cells = len(set(c["oracle"].cell[r.obs_idx].tolist()))
        out.append({"sample_id": c["sample"]["sample_id"], "iso_week": c["week"], "points": n, "cells": cells,
                    "U": c["oracle"].U, "abs_err": abs(float(np.mean(r.y_hat)) - float(np.mean(c["y"])))})
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--smoke", action="store_true", help="val weeks, 20 samples, counts only (no test data)")
    a = p.parse_args(argv)
    started = time.perf_counter()
    with open(PARQUET, "rb") as f:
        raw_sha = hashlib.sha256(f.read()).hexdigest()
    times, precip = load_cells(PARQUET)
    offsets, stamps = candidate_offsets(times, week_split(), "val" if a.smoke else "test")
    routes = data.load_routes()
    samples = draw_samples(routes, precip, offsets, stamps, np.random.default_rng(SEED))
    if a.smoke:
        samples = samples[:20]
    cases = make_cases(samples, routes)
    print(f"{len(cases)} samples on {len({(s['route_set'], s['route_id']) for s in samples})} routes "
          f"from {len(offsets)} candidate hours", flush=True)

    model, _ = final_eval.load_models()
    rows = tc.evaluate(cases, model, log=lambda m: print(m, flush=True))
    prev = previous_rows(cases)
    if a.smoke:
        print(f"smoke ok: {len(rows)} method rows, {len(prev)} previous rows (values not shown)")
        return 0
    mae, tests = tc.mae_table(rows), tc.tests_table(rows)
    for t, name in zip(tests, ("F-1", "F-2")):
        t["test"] = name
    by_week = {}
    for r in prev:
        by_week.setdefault(r["iso_week"], []).append(r["abs_err"])
    p_mean, p_lo, p_hi = tc.week_bootstrap_ci(by_week, B=tc.BOOT_B, seed=tc.BOOT_SEED)
    previous = [{"n": len(prev), "mean_points": float(np.mean([r["points"] for r in prev])),
                 "mean_cells": float(np.mean([r["cells"] for r in prev])),
                 "mean_U": float(np.mean([r["U"] for r in prev])), "mae": p_mean, "ci_lo": p_lo, "ci_hi": p_hi}]

    os.makedirs(OUT_DIR, exist_ok=True)
    tc.write_csv(os.path.join(OUT_DIR, "per_sample.csv.gz"), rows, opener=gzip.open)
    tc.write_csv(os.path.join(OUT_DIR, "mae.csv"), mae)
    tc.write_csv(os.path.join(OUT_DIR, "tests.csv"), tests)
    tc.write_csv(os.path.join(OUT_DIR, "previous.csv"), previous)
    summary = {
        "utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_head": (final_eval.git("rev-parse", "HEAD") or "").strip() or None,
        "data": "cells_forecast_d1.parquet", "data_sha256": raw_sha,
        "period": [str(times[0]), str(times[-1])], "split": "test",
        "n_samples": len(cases), "n_holdout_route_samples": sum(s["route_set"] == "holdout" for s in samples),
        "tests": tests, "previous": previous[0],
    }
    with open(os.path.join(OUT_DIR, "summary.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=2, default=float)
        f.write("\n")
    for r in tests:
        print(f"{r['test']} {r['a']} - {r['b']}: n={r['n']} mean diff {r['mean_diff']:.4f} "
              f"[{r['ci_lo']:.4f}, {r['ci_hi']:.4f}], p_holm {r['p_holm']:.3g} -> "
              f"{'supported' if r['supported'] else 'not supported'}", flush=True)
    print(f"done in {time.perf_counter() - started:.0f}s -> {OUT_DIR}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
