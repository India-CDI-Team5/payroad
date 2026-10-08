"""Fit the 12 GP configurations (6 kernels x 2 transforms) on the training split (ml-design v5 §3.3 steps 1-3).

Training data: wet training samples (any point above 0.1 mm), at most 2,000 drawn without replacement
with default_rng(seed), every other point (indices 0, 2, 4, …). Only the train split is read; choosing
a configuration is card B4's job, on the validation split.

Run from PartB/:
  python -m training.train_interpolator --seed 42 --out ../results/model_a/gp_candidates.json [--configs all] [--before YYYY-MM-DD]
"""
import os

# The likelihood factors thousands of ~25x25 matrices; multithreaded BLAS spends far more on thread
# hand-offs than on the work (10.7 s vs 0.16 s per evaluation measured on 16 cores). Must be set
# before numpy is imported.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402

from weather.data import WET_MM, load_routes, load_samples
from weather.gp import KERNELS, TRANSFORMS, features, fit

MAX_SAMPLES = 2000
CONFIGS = [f"{k}-{t}" for k in sorted(KERNELS) for t in TRANSFORMS]


def training_set(seed, before=None):
    """[(s, t, y)] of the chosen samples, already thinned to every other point."""
    routes = load_routes()
    rows = [r for r in load_samples(["train"]) if np.max(r["gt_mm"]) > WET_MM]
    if before is not None:
        cutoff = np.datetime64(before, "m")
        rows = [r for r in rows if np.datetime64(r["departure_utc"], "m") < cutoff]
    rng = np.random.default_rng(seed)
    if len(rows) > MAX_SAMPLES:
        rows = [rows[i] for i in rng.choice(len(rows), size=MAX_SAMPLES, replace=False)]
    out = []
    for r in rows:
        route = routes[(r["route_set"], r["route_id"])]
        idx = np.arange(0, len(r["gt_mm"]), 2)
        out.append((route["s_km"][idx], route["t_min"][idx], r["gt_mm"][idx]))
    return out


def fit_config(name, samples):
    kernel_key, transform = name.split("-", 1)
    kind, ard = KERNELS[kernel_key]
    g = TRANSFORMS[transform][0]
    datasets = []
    for s, t, y in samples:
        z = g(y)
        datasets.append((features(s, t, ard), z - z.mean()))
    params, nll, seconds = fit(datasets, kind, ard)
    return {"kernel": kind, "ard": ard, "transform": transform, "params": params, "nll": nll, "seconds": seconds}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", required=True)
    ap.add_argument("--configs", default="all", help="all, or a comma list such as K1-log1p,K3-identity")
    ap.add_argument("--before", default=None, help="only departures before this UTC date (YYYY-MM-DD)")
    args = ap.parse_args(argv)

    names = CONFIGS if args.configs == "all" else [c.strip() for c in args.configs.split(",") if c.strip()]
    unknown = [n for n in names if n not in CONFIGS]
    if unknown:
        ap.error(f"unknown configs {unknown}; expected names from {CONFIGS}")

    samples = training_set(args.seed, args.before)
    print(f"{len(samples)} training samples", flush=True)
    configs = {}
    start = time.perf_counter()
    for name in names:
        configs[name] = fit_config(name, samples)
        c = configs[name]
        print(f"{name}: nll={c['nll']:.2f} params={c['params']} {c['seconds']:.1f}s "
              f"(total {time.perf_counter() - start:.0f}s)", flush=True)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"seed": args.seed, "before": args.before, "n_samples": len(samples), "configs": configs},
                  f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
