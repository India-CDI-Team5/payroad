"""Where does the gain come from? Breakdown of the opened test results by route length, U and season (card B7).

Reads only results/model_a/test_per_sample.csv.gz written by training.final_eval: no test sample is
evaluated again and no model is applied. MAIN rows at rho = 0.5; CI = ISO-week block bootstrap
(B = 2000, seed 42, percentile), the same as final_eval.

Run from PartB/:  python -m training.breakdown
Writes ../results/model_a/breakdown_stratum.csv, breakdown_U.csv, breakdown_season.csv.
"""
import argparse
import csv
import gzip
import os

from weather.stats import week_bootstrap_ci

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "results", "model_a"))
PER_SAMPLE = "test_per_sample.csv.gz"

SUBSET = "MAIN"
RHO = "0.5"                      # as written by final_eval (str(0.5))
METHODS = ("B0", "B1", "B1-L", "B2", "B2-L", "M1", "M2")
BOOT_B, BOOT_SEED = 2000, 42
STRATA = ("short", "medium", "long")
SEASONS = ("sw_monsoon", "ne_monsoon", "dry")
U_BINS = ("3", "4-5", "6-7", "8+")


def u_bin(U):
    U = int(U)
    if U <= 3:
        return "3"
    if U <= 5:
        return "4-5"
    if U <= 7:
        return "6-7"
    return "8+"


# output file -> (group column, group of a row, group order)
TABLES = {
    "breakdown_stratum.csv": ("stratum", lambda r: r["stratum"], STRATA),
    "breakdown_U.csv": ("U_bin", lambda r: u_bin(r["U"]), U_BINS),
    "breakdown_season.csv": ("season", lambda r: r["season"], SEASONS),
}


def load_rows(path):
    """MAIN rows at rho = 0.5 (M1/M2 rows of the R-T model carry only the RT flag, so they drop out here)."""
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f)
                if SUBSET in r["subset_flags"].split("|") and r["rho"] == RHO]


def breakdown(rows, group_of, order):
    """One row per (group, method) with at least one sample: n, MAE and its week-block CI."""
    out = []
    for group in order:
        for method in METHODS:
            chosen = [r for r in rows if r["method"] == method and group_of(r) == group]
            if not chosen:
                continue
            by_week = {}
            for r in chosen:
                by_week.setdefault(r["iso_week"], []).append(float(r["abs_err"]))
            mae, lo, hi = week_bootstrap_ci(by_week, B=BOOT_B, seed=BOOT_SEED)
            out.append({"group": group, "method": method, "n": len(chosen), "mae": mae, "ci_lo": lo, "ci_hi": hi})
    return out


def write(path, group_column, table):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow([group_column, "method", "rho", "n", "mae", "ci_lo", "ci_hi"])
        for r in table:
            w.writerow([r["group"], r["method"], RHO, r["n"], f"{r['mae']:.6f}", f"{r['ci_lo']:.6f}", f"{r['ci_hi']:.6f}"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results-dir", default=RESULTS_DIR, help="reads test_per_sample.csv.gz here and writes next to it")
    args = ap.parse_args(argv)
    rows = load_rows(os.path.join(args.results_dir, PER_SAMPLE))
    print(f"{len({r['sample_id'] for r in rows})} MAIN samples at rho = {RHO}")
    for name, (column, group_of, order) in TABLES.items():
        path = os.path.join(args.results_dir, name)
        write(path, column, breakdown(rows, group_of, order))
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
