"""Bot self-diagnostics before freezing bot-params.json (ml-design v5 §6.5, card C3).

Run from the repository root after
  ./gradlew runExperiment --args="--scenario e2"
  ./gradlew runExperiment --args="--scenario diag-var"
(both from PartA/):
  python scripts/sim/diagnostics.py

(a) variance test: std of markup over the MATCHED deals of diag-var (one deal, n = 5, C1, seed 1~100).
(b) explanatory-power test: OLS of markup on [winner_pickup_eta, beta, base_price, distance_km]
    + intercept over the MATCHED e2 deals (n is fixed at 5 there, so it is left out).
    MATCHED deals whose winner_pickup_eta is empty (the winner took the offer without a bid) are dropped.
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np

STD_MIN = 0.01
R2_MAX = 0.95
R2_HEALTHY = (0.3, 0.6)
FEATURES = ["winner_pickup_eta", "beta", "base_price", "distance_km"]


def read_matched(path):
    """The MATCHED rows of a deals_out.csv, as dicts of strings."""
    with open(path, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["status"] == "MATCHED"]


def var_test(rows):
    markup = np.array([float(r["markup"]) for r in rows])
    std = float(np.std(markup, ddof=1)) if len(markup) > 1 else 0.0
    return {"n": len(markup), "std_markup": std, "pass": bool(std > STD_MIN)}


def r2_test(rows):
    rows = [r for r in rows if all(r[c] != "" for c in FEATURES + ["markup"])]
    y = np.array([float(r["markup"]) for r in rows])
    X = np.column_stack([np.array([float(r[c]) for r in rows]) for c in FEATURES] + [np.ones(len(rows))])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    ss_res = float(np.sum((y - X @ coef) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return {"n": len(rows), "r2": r2, "pass": bool(r2 < R2_MAX),
            "healthy": bool(R2_HEALTHY[0] <= r2 <= R2_HEALTHY[1])}


def run(diag_path, e2_path):
    return {"var_test": var_test(read_matched(diag_path)), "r2_test": r2_test(read_matched(e2_path))}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--diag", default="results/sim/raw/diag-var/deals_out.csv")
    p.add_argument("--e2", default="results/sim/raw/e2/deals_out.csv")
    p.add_argument("--out", default="results/sim/diagnostics.json")
    a = p.parse_args()
    result = run(a.diag, a.e2)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
