"""Validation of Model A (ml-design v5 §3.3 steps 4-6, §4.2): pick one GP configuration and the variance
scale kappa on the validation split, then tabulate every method there.

Only the validation split exists here: --split accepts "val" and nothing else (the test split is opened
once, after the freeze commit, by a later card).

Run from PartB/:  python -m training.eval_interpolator --split val --select
  --select  (a) M1 validation MAE of the 12 candidates -> configuration (tie rule of §3.3 step 5),
            (b) kappa whose point coverage is closest to 0.95, (c) writes models/gp_interpolator.json.
  always    (d) writes ../results/model_a/val_table.csv (7 methods x rho x {MAIN, ALL, LONG}).
"""
import os

# Thousands of small posteriors: multithreaded BLAS costs more than it saves (see train_interpolator).
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import csv  # noqa: E402
import datetime  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402

from weather.data import in_subset, load_routes, load_samples  # noqa: E402
from weather.methods import run  # noqa: E402
from weather.metrics import abs_err_mean, max_hit, spearman, surcharge  # noqa: E402
from weather.oracle import RouteOracle  # noqa: E402
from weather.selection import budget  # noqa: E402

HERE = os.path.dirname(__file__)
CANDIDATES = os.path.join(HERE, "..", "..", "results", "model_a", "gp_candidates.json")
MODEL_PATH = os.path.join(HERE, "..", "models", "gp_interpolator.json")
VAL_TABLE = os.path.join(HERE, "..", "..", "results", "model_a", "val_table.csv")

SELECT_RHOS = (0.25, 0.5, 0.75)
TABLE_RHOS = (0.25, 0.5, 0.75, 1.0)
METHODS = ("B0", "B1", "B1-L", "B2", "B2-L", "M1", "M2")
GP_METHODS = ("M1", "M2")
TABLE_SUBSETS = ("MAIN", "ALL", "LONG")
KAPPAS = [round(0.50 + 0.05 * i, 2) for i in range(51)]          # 0.50, 0.55, ..., 3.00
TIE_TOLERANCE = 1.01
DRAWS = 500
COLUMNS = ("method", "rho", "subset", "n", "mae", "max_hit_rate", "surcharge_agree",
           "cov_points", "cov_mean", "spearman_s_err")

# §3.3 step 5: fewer parameters -> one axis -> RBF -> larger-nu Matern -> log1p.
KIND_RANK = {"rbf": 0, "matern25": 1, "matern15": 2, "matern05": 3}
TRANSFORM_RANK = {"log1p": 0, "identity": 1}


def load_cases(split):
    """Every validation sample with its route arrays; U >= 3 filtering happens per subset."""
    routes = load_routes()
    cases = []
    for smp in load_samples([split]):
        route = routes[(smp["route_set"], smp["route_id"])]
        cases.append({"sample": smp, "route": route, "y": smp["gt_mm"],
                      "oracle": RouteOracle(route["cell"], smp["gt_mm"]),
                      "s": route["s_km"], "t": route["t_min"]})
    return cases


def model_of(config, kappa):
    return {"kernel": config["kernel"], "ard": config["ard"], "transform": config["transform"],
            "params": config["params"], "kappa": kappa}


def m1_val_mae(cases, model):
    """MAE of M1 per rho, averaged over rho in {0.25, 0.5, 0.75}."""
    per_rho = []
    for rho in SELECT_RHOS:
        errs = [abs_err_mean(run("M1", c["oracle"], c["s"], c["t"], budget(c["oracle"].U, rho), model).y_hat, c["y"])
                for c in cases]
        per_rho.append(float(np.mean(errs)))
    return float(np.mean(per_rho))


def tie_key(config):
    return (len(config["params"]), int(config["ard"]), KIND_RANK[config["kernel"]], TRANSFORM_RANK[config["transform"]])


def choose(configs, maes):
    best = min(maes.values())
    eligible = [name for name in configs if maes[name] <= best * TIE_TOLERANCE]
    return min(eligible, key=lambda name: tie_key(configs[name]))


def kappa_curve(cases, config):
    """Pooled 95% point coverage over every unobserved point, for each kappa."""
    curve = []
    for kappa in KAPPAS:
        model = model_of(config, kappa)
        inside = total = 0
        for rho in SELECT_RHOS:
            for c in cases:
                r = run("M1", c["oracle"], c["s"], c["t"], budget(c["oracle"].U, rho), model)
                mask = np.ones(len(c["y"]), dtype=bool)
                mask[r.obs_idx] = False
                inside += int(((r.lo <= c["y"]) & (c["y"] <= r.hi))[mask].sum())
                total += int(mask.sum())
        curve.append({"kappa": kappa, "coverage": inside / total})
    return curve


def choose_kappa(curve):
    return min(curve, key=lambda p: (abs(p["coverage"] - 0.95), p["kappa"]))


def select(cases_main, candidates):
    configs = candidates["configs"]
    maes = {}
    for name in sorted(configs):
        start = time.perf_counter()
        maes[name] = m1_val_mae(cases_main, model_of(configs[name], 1.0))
        print(f"  {name}: val_mae={maes[name]:.6f} ({time.perf_counter() - start:.0f}s)", flush=True)
    chosen = choose(configs, maes)
    print(f"selected {chosen}", flush=True)
    curve = kappa_curve(cases_main, configs[chosen])
    best = choose_kappa(curve)
    print(f"kappa={best['kappa']} coverage={best['coverage']:.4f}", flush=True)
    cfg = configs[chosen]
    return {
        "config": chosen, "kernel": cfg["kernel"], "ard": cfg["ard"], "transform": cfg["transform"],
        "params": cfg["params"], "kappa": best["kappa"],
        "n_train_samples": candidates["n_samples"], "fit_seconds": cfg["seconds"],
        "selection": [{"config": name, "val_mae": maes[name]} for name in sorted(configs)],
        "kappa_curve": curve,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def per_sample(case, method, rho, model):
    y = case["y"]
    o = case["oracle"]
    gp = method in GP_METHODS
    r = run(method, o, case["s"], case["t"], budget(o.U, rho), model=model if gp else None,
            sample_id=case["sample"]["sample_id"], draws=DRAWS if gp else 0)
    row = {"err": abs_err_mean(r.y_hat, y), "max_hit": max_hit(r.y_hat, y, o.cell),
           "agree": surcharge(float(np.mean(r.y_hat))) == surcharge(float(np.mean(y)))}
    if gp:
        mask = np.ones(len(y), dtype=bool)
        mask[r.obs_idx] = False
        row["n_unobs"] = int(mask.sum())
        row["n_in"] = int(((r.lo <= y) & (y <= r.hi))[mask].sum())
        lo, hi = np.percentile(r.mean_draws, [2.5, 97.5])
        row["mean_in"] = bool(lo <= np.mean(y) <= hi)
        row["s"] = float(np.std(r.mean_draws))
    return row


def aggregate(rows, gp):
    out = {"n": len(rows), "mae": float(np.mean([r["err"] for r in rows]))}
    hits = [r["max_hit"] for r in rows if r["max_hit"] is not None]
    out["max_hit_rate"] = float(np.mean(hits)) if hits else None
    out["surcharge_agree"] = float(np.mean([r["agree"] for r in rows]))
    out["cov_points"] = out["cov_mean"] = out["spearman_s_err"] = None
    if gp:
        open_rows = [r for r in rows if r["n_unobs"] > 0]           # rho = 1.0 leaves nothing to cover
        if open_rows:
            out["cov_points"] = sum(r["n_in"] for r in open_rows) / sum(r["n_unobs"] for r in open_rows)
            out["cov_mean"] = float(np.mean([r["mean_in"] for r in open_rows]))
            s = [r["s"] for r in open_rows]
            if len(open_rows) >= 3 and np.ptp(s) > 0:
                out["spearman_s_err"] = float(spearman(s, [r["err"] for r in open_rows]))
    return out


def val_table(cases, model):
    """Each (sample, method, rho) is run once and shared by the subsets that contain the sample."""
    cases = [c for c in cases if in_subset(c["sample"], c["route"], "ALL")]
    membership = {name: [in_subset(c["sample"], c["route"], name) for c in cases] for name in TABLE_SUBSETS}
    table = []
    for method in METHODS:
        for rho in TABLE_RHOS:
            start = time.perf_counter()
            rows = [per_sample(c, method, rho, model) for c in cases]
            for name in TABLE_SUBSETS:
                chosen = [r for r, keep in zip(rows, membership[name]) if keep]
                table.append({"method": method, "rho": rho, "subset": name,
                              **aggregate(chosen, method in GP_METHODS)})
            print(f"  {method} rho={rho}: {time.perf_counter() - start:.0f}s", flush=True)
    return table


def write_table(table, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for row in table:
            w.writerow(["" if row[c] is None else (f"{row[c]:.6f}" if isinstance(row[c], float) and c != "rho"
                                                  else row[c]) for c in COLUMNS])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--split", required=True, choices=["val"], help="validation only; the test split is not opened here")
    ap.add_argument("--select", action="store_true", help="choose configuration and kappa, write models/gp_interpolator.json")
    args = ap.parse_args(argv)

    start = time.perf_counter()
    cases = load_cases(args.split)
    main_cases = [c for c in cases if in_subset(c["sample"], c["route"], "MAIN")]
    print(f"{len(cases)} {args.split} samples, {len(main_cases)} MAIN", flush=True)

    if args.select:
        with open(CANDIDATES, encoding="utf-8") as f:
            candidates = json.load(f)
        chosen = select(main_cases, candidates)
        os.makedirs(os.path.dirname(os.path.abspath(MODEL_PATH)), exist_ok=True)
        with open(MODEL_PATH, "w", encoding="utf-8") as f:
            json.dump(chosen, f, indent=2, sort_keys=True)
            f.write("\n")
        print(f"wrote {MODEL_PATH}", flush=True)
    with open(MODEL_PATH, encoding="utf-8") as f:
        stored = json.load(f)

    table = val_table(cases, model_of(stored, stored["kappa"]))
    write_table(table, VAL_TABLE)
    print(f"wrote {VAL_TABLE} ({time.perf_counter() - start:.0f}s total)", flush=True)


if __name__ == "__main__":
    main()
