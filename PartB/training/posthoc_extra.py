"""Post-hoc additions for the third review round (paper-revision-v1 X15). Reads frozen results, never writes them.

The test split was opened on 2026-10-08 (card B6); everything here is post hoc and descriptive (no new tests).
  previous_mae.csv     the previous system's queries on the same samples: determine_sample_count(distance) points
                       (4/6/9/12, evenly spaced, both ends included) read with the nearest value, i.e. B1's placement
                       and fill with the old point count instead of a budget. MAIN and HOLDOUT, with week-bootstrap CIs
                       and the mean number of points (= calls) and of distinct cells.
  kbin_mae.csv         MAE by k (1, 2, >= 3) at every rho, from placement_per_sample.csv.gz (X2 output).
  surcharge_kappa.csv  surcharge decision beta(r, 0) > threshold against the truth on MAIN at rho = 0.5, from
                       test_per_sample.csv.gz: base rate, agreement, recall, precision, F1 and Cohen's kappa.

Run from PartB/ (the first table reads parquet, so inside Docker on this PC):
    python -m training.posthoc_extra [--out-dir DIR]
"""
import os

for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import csv  # noqa: E402
import gzip  # noqa: E402
import sys  # noqa: E402

import numpy as np  # noqa: E402

from training import final_eval  # noqa: E402
from weather.methods import run  # noqa: E402
from weather.stats import week_bootstrap_ci  # noqa: E402

DEFAULT_OUT_DIR = os.path.join(final_eval.ROOT, "results", "posthoc", "model_a")
SUBSETS = ("MAIN", "HOLDOUT")
KBIN_METHODS = ("B1", "M1", "M2", "H-P")
COLUMNS = {
    "previous_mae.csv": ("subset", "n", "mean_points", "mean_cells", "mae", "ci_lo", "ci_hi"),
    "kbin_mae.csv": ("subset", "rho", "k_bin", "method", "n", "mae"),
    "surcharge_kappa.csv": ("method", "n", "base_rate", "agreement", "recall", "precision", "f1", "kappa"),
}


def sample_count(distance_km):
    """The previous sampler's point count (PartB/sampler.determine_sample_count), copied to avoid its HTTP imports."""
    if distance_km < 10:
        return 4
    if distance_km < 30:
        return 6
    if distance_km < 60:
        return 9
    return 12


def previous_rows(cases):
    """Per sample: (subset, week, points, distinct cells, abs_err) of the previous system's queries."""
    out = []
    for c in cases:
        subset = next((x for x in SUBSETS if x in c["flags"]), None)
        if subset is None:
            continue
        P = len(c["s"])
        n = min(sample_count(c["route"]["distance_km"]), P)
        r = run("B1", c["oracle"], c["s"], c["t"], n)
        cells = len(set(c["oracle"].cell[r.obs_idx].tolist()))
        out.append((subset, c["week"], n, cells, abs(float(np.mean(r.y_hat)) - float(np.mean(c["y"])))))
    return out


def previous_table(rows):
    table = []
    for subset in SUBSETS:
        rs = [r for r in rows if r[0] == subset]
        if not rs:
            continue
        by_week = {}
        for r in rs:
            by_week.setdefault(r[1], []).append(r[4])
        mae, lo, hi = week_bootstrap_ci(by_week)
        table.append({"subset": subset, "n": len(rs), "mean_points": float(np.mean([r[2] for r in rs])),
                      "mean_cells": float(np.mean([r[3] for r in rs])), "mae": mae, "ci_lo": lo, "ci_hi": hi})
    return table


def k_bin(k):
    return "1" if k == 1 else "2" if k == 2 else ">=3"


def kbin_table(per_sample_path):
    acc = {}
    with gzip.open(per_sample_path, "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["method"] in KBIN_METHODS:
                acc.setdefault((r["subset"], r["rho"], k_bin(int(r["k"])), r["method"]), []).append(float(r["abs_err"]))
    order = {"1": 0, "2": 1, ">=3": 2}
    keys = sorted(acc, key=lambda x: (SUBSETS.index(x[0]), float(x[1]), order[x[2]], KBIN_METHODS.index(x[3])))
    return [{"subset": s, "rho": rho, "k_bin": kb, "method": m, "n": len(acc[(s, rho, kb, m)]),
             "mae": float(np.mean(acc[(s, rho, kb, m)]))} for s, rho, kb, m in keys]


def kappa_row(method, truth, pred):
    y, f = np.asarray(truth, dtype=bool), np.asarray(pred, dtype=bool)
    n = len(y)
    tp, fp, fn = int((y & f).sum()), int((~y & f).sum()), int((y & ~f).sum())
    tn = n - tp - fp - fn
    po = (tp + tn) / n
    pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / n ** 2
    recall = tp / (tp + fn) if tp + fn else float("nan")
    precision = tp / (tp + fp) if tp + fp else float("nan")
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else float("nan")
    return {"method": method, "n": n, "base_rate": float(y.mean()), "agreement": po, "recall": recall,
            "precision": precision, "f1": f1, "kappa": (po - pe) / (1 - pe) if pe < 1 else float("nan")}


def surcharge_table(per_sample_path, rho="0.5"):
    acc = {}
    with gzip.open(per_sample_path, "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["rho"] == rho and "MAIN" in r["subset_flags"].split("|"):
                t, p = acc.setdefault(r["method"], ([], []))
                t.append(r["flag_true"] == "1")
                p.append(r["flag_beta_r"] == "1")
    return [kappa_row(m, *acc[m]) for m in acc]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default=final_eval.DEFAULT_DATA_DIR)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--frozen-dir", default=final_eval.DEFAULT_RESULTS_DIR)
    ap.add_argument("--placement", default=os.path.join(DEFAULT_OUT_DIR, "placement_per_sample.csv.gz"))
    args = ap.parse_args(argv)

    cases = final_eval.load_cases(args.data_dir)
    tables = {"previous_mae.csv": previous_table(previous_rows(cases)),
              "kbin_mae.csv": kbin_table(args.placement),
              "surcharge_kappa.csv": surcharge_table(os.path.join(args.frozen_dir, "test_per_sample.csv.gz"))}
    os.makedirs(args.out_dir, exist_ok=True)
    for name, table in tables.items():
        final_eval.write_csv(os.path.join(args.out_dir, name), COLUMNS[name], table)
        print(f"{name}: {len(table)} rows", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
