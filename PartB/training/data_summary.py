"""Data numbers for the paper, as a small JSON that can be committed (the parquet files cannot).

Reads data/routes.parquet, data/routes_holdout.parquet, data/cells.parquet and data/samples.parquet
(made by route_generator, collect_groundtruth and build_samples) and only counts; it changes nothing.

Run from PartB/:  python -m training.data_summary
Writes ../results/model_a/data_summary.json.
"""
import json
import os

import numpy as np
import pyarrow.compute as pc
import pyarrow.parquet as pq

from training.build_samples import G1_MIN_SHARE_U_GE_3, G1_MIN_WET_SHARE, WET_MM

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "results", "model_a", "data_summary.json")
STRATA = ("short", "medium", "long")
SPLITS = ("train", "val", "test", "test_holdout")


def route_stats(path):
    t = pq.read_table(path, columns=["stratum", "distance_km", "unique_cells"])
    stratum = np.array(t.column("stratum").to_pylist())
    u = t.column("unique_cells").to_numpy()
    km = t.column("distance_km").to_numpy()
    values, counts = np.unique(u, return_counts=True)
    return {
        "n": int(t.num_rows),
        "by_stratum": {s: int((stratum == s).sum()) for s in STRATA},
        "U_hist": {str(int(v)): int(c) for v, c in zip(values, counts)},
        "share_U_ge_3": round(float((u >= 3).mean()), 3),
        "distance_km": {"min": round(float(km.min()), 3), "median": round(float(np.median(km)), 3),
                        "max": round(float(km.max()), 3)},
    }


def cell_stats(path):
    t = pq.read_table(path, columns=["time_utc", "precipitation_mm"])
    times = t.column("time_utc")[0].as_py()
    precip = pc.list_flatten(t.column("precipitation_mm")).to_numpy(zero_copy_only=False).astype(float)
    precip = precip[~np.isnan(precip)]                    # missing hours (None) are not counted
    return {
        "n": int(t.num_rows),
        "hours": len(times),
        "period_utc": [times[0], times[-1]],
        "wet_hour_share_gt_0.1": round(float((precip > WET_MM).mean()), 4),
    }


def sample_stats(path):
    t = pq.read_table(path, columns=["route_set", "split", "departure_local", "season", "wet"])
    split = np.array(t.column("split").to_pylist())
    wet = t.column("wet").to_numpy(zero_copy_only=False)
    main = np.array(t.column("route_set").to_pylist()) == "main"
    season = np.array(t.column("season").to_pylist())
    days = np.array(t.column("departure_local").to_pylist(), dtype="datetime64[D]").astype(object)
    weeks = np.array([f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}" for d in days])
    return {
        "by_split": {s: int((split == s).sum()) for s in SPLITS},
        "wet_share_by_split": {s: round(float(wet[split == s].mean()), 3) if (split == s).any() else None
                               for s in SPLITS},
        # Main routes only, as in samples_summary.json (holdout departures come from test weeks only).
        "dry_season_share": round(float((season[main] == "dry").mean()), 3),
        "iso_weeks_by_split": {s: len(set(weeks[split == s])) for s in SPLITS},
    }


def g1(routes_main, samples_path):
    t = pq.read_table(samples_path, columns=["route_set", "wet"])
    main = np.array(t.column("route_set").to_pylist()) == "main"
    wet_share = round(float(t.column("wet").to_numpy(zero_copy_only=False)[main].mean()), 3)
    share_u3 = routes_main["share_U_ge_3"]
    return {"pass": bool(share_u3 >= G1_MIN_SHARE_U_GE_3 and wet_share >= G1_MIN_WET_SHARE),
            "share_U_ge_3": share_u3, "wet_share": wet_share}


def summarize(data_dir):
    routes_main = route_stats(os.path.join(data_dir, "routes.parquet"))
    samples_path = os.path.join(data_dir, "samples.parquet")
    return {
        "routes_main": routes_main,
        "routes_holdout": route_stats(os.path.join(data_dir, "routes_holdout.parquet")),
        "cells": cell_stats(os.path.join(data_dir, "cells.parquet")),
        "samples": sample_stats(samples_path),
        "G1": g1(routes_main, samples_path),
    }


def main():
    summary = summarize(DATA_DIR)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
