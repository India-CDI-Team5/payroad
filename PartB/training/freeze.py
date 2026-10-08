"""Pre-registration of Model A (card B5): fix the evaluation plan and the hashes of every input it depends
on, before the test split is opened.

Hashes are SHA-256 of the raw file bytes of the selected GP (models/gp_interpolator.json), the R-T
hyperparameters (results/model_a/gp_rt.json) and the pricing constants (config/pricing-constants.json).
This script only reads those files; it never rewrites them, and it reads no samples at all.

Run from PartB/:  python -m training.freeze
Writes configs/model_a_frozen.json. Running it again gives the same file except frozen_utc.
"""
import argparse
import datetime
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
OUT_PATH = os.path.join(ROOT, "PartB", "configs", "model_a_frozen.json")

HASHED = {
    "gp_interpolator_sha256": os.path.join(ROOT, "PartB", "models", "gp_interpolator.json"),
    "gp_rt_sha256": os.path.join(ROOT, "results", "model_a", "gp_rt.json"),
    "pricing_constants_sha256": os.path.join(ROOT, "config", "pricing-constants.json"),
}

# ml-design v5 §1.3, §3.1, §4.1-§4.3, §5.2. Changing any of this after the freeze commit breaks the pre-registration.
PLAN = {
    "rhos": [0.25, 0.5, 0.75, 1.0],
    "k_abs": [1, 2, 3, 4, 5, 6, 7, 8],
    "methods": ["B0", "B1", "B1-L", "B2", "B2-L", "M1", "M2"],
    "subsets": ["MAIN", "ALL", "LONG", "HOLDOUT", "RT"],
    "draws": 500,
    "draw_seed_rule": "42+sample_id",
    "pairs": [["B2", "B1"], ["M1", "B2-L"], ["M1", "B1"], ["M2", "M1"]],
    "pair_rhos": [0.25, 0.5, 0.75],
    "test": "wilcoxon two-sided zero_method=wilcox",
    "correction": "holm",
    "alpha": 0.05,
    "bootstrap": {"unit": "iso_week", "B": 2000, "seed": 42, "ci": "percentile"},
    "uncertainty_bins": 5,
    "saving_rho_grid_step": 0.05,
    "beta_compare_rho": 0.5,
}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def frozen(now=None, hashed=HASHED):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    record = {"frozen_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    for key, path in hashed.items():
        record[key] = sha256_file(path)
    record.update(PLAN)
    return record


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=OUT_PATH)
    args = ap.parse_args(argv)
    record = frozen()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(record, f, indent=2)
        f.write("\n")
    for key in HASHED:
        print(f"{key}: {record[key]}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
