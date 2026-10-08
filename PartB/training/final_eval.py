"""Final evaluation of Model A (card B6, ml-design v5 §4-§5): the test split and the holdout routes, opened once.

Run from PartB/, once, by a person, on the card/b6-open branch:
    python -m training.final_eval --confirm-open-test

Start checks (any failure -> exit code 2 before any data is read):
  (a) --confirm-open-test is given
  (b) <results-dir>/TEST_OPENED.json does not exist (the test is opened only once)
  (c) git status shows no change to tracked files
  (d) the three SHA-256 in configs/model_a_frozen.json match the current files
Then TEST_OPENED.json is written *before* any computation, so a crash cannot be retried silently.

Test mode: when --data-dir or --results-dir is not its default, (c) and (d) are skipped. Tests always use
tmp paths for both, so they never write the real results/model_a/TEST_OPENED.json.

Everything the computation follows comes from the frozen plan (configs/model_a_frozen.json), the frozen
models (models/gp_interpolator.json, results/model_a/gp_rt.json) and config/pricing-constants.json.
Nothing here may be tuned after looking at the output.

test_per_sample.csv.gz has one row per (sample, method, grid point, model). Grid points are rho rows
(rho set, k = budget(U, rho)) and k_abs rows (rho empty, k <= U). subset_flags lists the subsets the row
counts for: M1/M2 rows with the main model never carry RT, and a sample of the R-T subset gets extra M1/M2
rows computed with the gp_rt.json hyperparameters (same kappa) whose only flag is RT.
"""
import os

# Thousands of small posteriors: multithreaded BLAS costs more than it saves (see train_interpolator).
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import csv  # noqa: E402
import datetime  # noqa: E402
import gzip  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402

from training import freeze  # noqa: E402
from weather import data  # noqa: E402
from weather.data import in_subset, iso_week  # noqa: E402
from weather.methods import run  # noqa: E402
from weather.metrics import beta, max_hit, spearman  # noqa: E402
from weather.oracle import RouteOracle  # noqa: E402
from weather.selection import budget, select_b1  # noqa: E402
from weather.stats import holm, week_bootstrap_ci, wilcoxon_pair  # noqa: E402

ROOT = freeze.ROOT
DEFAULT_DATA_DIR = os.path.normpath(data.DATA_DIR)
DEFAULT_RESULTS_DIR = os.path.join(ROOT, "results", "model_a")
FROZEN_PATH = freeze.OUT_PATH
HASHED = freeze.HASHED
MODEL_PATH = HASHED["gp_interpolator_sha256"]
RT_PATH = HASHED["gp_rt_sha256"]
PRICING_PATH = HASHED["pricing_constants_sha256"]
OPENED_NAME = "TEST_OPENED.json"

SPLITS = ("test", "test_holdout")
GP_METHODS = ("M1", "M2")
RT_FROM = np.datetime64("2025-01-01T00:00", "m")      # ml-design v5 §2.3: R-T evaluates 2025 departures

PER_SAMPLE_COLUMNS = (
    "sample_id", "split", "route_set", "route_id", "stratum", "U", "distance_km", "iso_week", "season", "wet",
    "subset_flags", "method", "rho", "k", "calls", "m_true", "m_hat", "abs_err", "max_hit", "s_mean",
    "cov_points_num", "cov_points_den", "cov_mean", "flag_true", "flag_beta_r", "flag_beta_rs", "b1_duplicate_rate")
COLUMNS = {
    "F1_curve.csv": ("subset", "method", "rho", "n", "mae", "ci_lo", "ci_hi"),
    "F1_kabs.csv": ("subset", "method", "k", "n", "mae", "ci_lo", "ci_hi"),
    "T1_table.csv": ("subset", "method", "n", "mae_rho25", "mae_rho50", "mae_rho75", "ci50_lo", "ci50_hi",
                     "max_hit_rho50", "agree_rho50", "saving_vs_B1"),
    "F2_coverage.csv": ("method", "rho", "n", "cov_points", "cov_mean"),
    "F2_uncertainty_bins.csv": ("method", "rho", "bin", "s_lo", "s_hi", "n", "mean_abs_err"),
    "F2_spearman.csv": ("method", "rho", "n", "spearman"),
    "F2_beta_compare.csv": ("rule", "n", "agree", "over_rate", "under_rate"),
    "T2_beta_sensitivity.csv": ("coef", "method", "n", "agree", "over_rate", "under_rate", "rank"),
    "stats_tests.csv": ("a", "b", "rho", "n", "mean_diff", "ci_lo", "ci_hi", "median_diff", "p", "p_holm",
                        "significant"),
    "B1_duplicate.csv": ("rho", "n", "mean_duplicate_rate"),
}
HEADLINE_METHODS = ("M1", "B1", "B2-L", "M2")


# ----------------------------------------------------------------------------------------------------------
# start checks
# ----------------------------------------------------------------------------------------------------------

def git(*args):
    """stdout of a git command in the repository, or None when git cannot be run or fails."""
    try:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    except OSError:
        return None
    return r.stdout if r.returncode == 0 else None


def tracked_changes():
    """Changed tracked files as `git status --porcelain` lines; None when git is unavailable."""
    out = git("status", "--porcelain", "--untracked-files=no")
    return None if out is None else [line for line in out.splitlines() if line.strip()]


def hash_mismatches(frozen_path=None, hashed=None):
    """Keys of the frozen record whose file is missing or hashes differently now."""
    frozen_path = frozen_path or FROZEN_PATH
    hashed = hashed or HASHED
    with open(frozen_path, encoding="utf-8") as f:
        record = json.load(f)
    bad = []
    for key, path in hashed.items():
        if not os.path.exists(path) or record.get(key) != freeze.sha256_file(path):
            bad.append(key)
    return bad


def is_test_mode(data_dir, results_dir):
    same = lambda a, b: os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))  # noqa: E731
    return not (same(data_dir, DEFAULT_DATA_DIR) and same(results_dir, DEFAULT_RESULTS_DIR))


def preflight(confirmed, results_dir, test_mode):
    """None when every check passes, otherwise the reason of the first failure."""
    if not confirmed:
        return "--confirm-open-test 인자가 없습니다 (테스트는 한 번만 엽니다)"
    if os.path.exists(os.path.join(results_dir, OPENED_NAME)):
        return f"{OPENED_NAME}이 이미 있습니다: 테스트는 이미 개봉되었습니다"
    if test_mode:
        return None
    changes = tracked_changes()
    if changes is None:
        return "git을 실행할 수 없어 작업 트리를 확인하지 못했습니다"
    if changes:
        return "추적 파일에 커밋하지 않은 변경이 있습니다:\n  " + "\n  ".join(changes)
    bad = hash_mismatches()
    if bad:
        return "동결 파일의 SHA-256이 현재 파일과 다릅니다: " + ", ".join(bad)
    return None


def write_opened(results_dir):
    with open(FROZEN_PATH, encoding="utf-8") as f:
        record = json.load(f)
    head = git("rev-parse", "HEAD")
    opened = {
        "opened_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_head": head.strip() if head else None,
        "frozen_sha256": {key: record.get(key) for key in HASHED},
    }
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, OPENED_NAME), "x", encoding="utf-8", newline="\n") as f:
        json.dump(opened, f, indent=2)
        f.write("\n")


# ----------------------------------------------------------------------------------------------------------
# inputs
# ----------------------------------------------------------------------------------------------------------

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_models():
    """Main model (models/gp_interpolator.json) and the R-T model: gp_rt.json hyperparameters, same kappa."""
    main = load_json(MODEL_PATH)
    rt = load_json(RT_PATH)["configs"]
    rt_cfg = rt[main["config"]] if main["config"] in rt else next(iter(rt.values()))
    keys = ("kernel", "ard", "transform", "params")
    return ({**{k: main[k] for k in keys}, "kappa": main["kappa"]},
            {**{k: rt_cfg[k] for k in keys}, "kappa": main["kappa"]})


def load_cases(data_dir):
    saved, data.DATA_DIR = data.DATA_DIR, data_dir     # weather.data reads its directory at call time
    try:
        routes = data.load_routes()
        samples = data.load_samples(list(SPLITS))
    finally:
        data.DATA_DIR = saved
    cases = []
    for smp in samples:
        route = routes[(smp["route_set"], smp["route_id"])]
        y = smp["gt_mm"]
        wet = bool(np.max(y) > data.WET_MM)
        flags = set()
        if smp["split"] == "test":
            for name in ("MAIN", "ALL", "LONG"):
                if in_subset(smp, route, name):
                    flags.add(name)
            if route["unique_cells"] >= 3 and wet and np.datetime64(smp["departure_utc"], "m") >= RT_FROM:
                flags.add("RT")
        elif in_subset(smp, route, "HOLDOUT"):
            flags.add("HOLDOUT")
        year, week = iso_week(smp["departure_utc"])
        cases.append({"sample": smp, "route": route, "y": y, "oracle": RouteOracle(route["cell"], y),
                      "s": route["s_km"], "t": route["t_min"], "wet": wet, "flags": flags,
                      "week": f"{year}-W{week:02d}"})
    cases.sort(key=lambda c: c["sample"]["sample_id"])
    return cases


# ----------------------------------------------------------------------------------------------------------
# per-sample rows
# ----------------------------------------------------------------------------------------------------------

class Pricing:
    def __init__(self, constants):
        self.coef = constants["betaCoef"]
        self.cap = constants["betaCap"]
        self.w = constants["uncertaintyWeight"]
        self.thr = constants["surchargeThreshold"]
        self.sensitivity = constants["betaSensitivity"]

    def flag(self, r, s=0.0, coef=None):
        return beta(r, s, self.coef if coef is None else coef, self.cap, self.w) > self.thr


def grid(case, plan):
    U = case["oracle"].U
    points = [(rho, budget(U, rho)) for rho in plan["rhos"]]
    points += [(None, k) for k in plan["k_abs"] if k <= U]
    return points


def evaluate(case, method, rho, k, model, draws, pricing, flags):
    y, o = case["y"], case["oracle"]
    gp = method in GP_METHODS
    r = run(method, o, case["s"], case["t"], k, model=model if gp else None,
            sample_id=case["sample"]["sample_id"], draws=draws if gp else 0)
    m_true, m_hat = float(np.mean(y)), float(np.mean(r.y_hat))
    smp, route = case["sample"], case["route"]
    row = {
        "sample_id": smp["sample_id"], "split": smp["split"], "route_set": smp["route_set"],
        "route_id": smp["route_id"], "stratum": route["stratum"], "U": o.U, "distance_km": route["distance_km"],
        "iso_week": case["week"], "season": smp["season"], "wet": case["wet"], "flags": frozenset(flags),
        "method": method, "rho": rho, "k": k, "calls": r.calls, "m_true": m_true, "m_hat": m_hat,
        "abs_err": abs(m_hat - m_true), "max_hit": max_hit(r.y_hat, y, o.cell),
        "s_mean": None, "cov_points_num": None, "cov_points_den": None, "cov_mean": None,
        "flag_true": pricing.flag(m_true), "flag_beta_r": pricing.flag(m_hat), "flag_beta_rs": None,
        "b1_duplicate_rate": None,
    }
    if gp:
        mask = np.ones(len(y), dtype=bool)
        mask[r.obs_idx] = False
        row["cov_points_den"] = int(mask.sum())
        row["cov_points_num"] = int(((r.lo <= y) & (y <= r.hi))[mask].sum())
        if draws > 0:
            row["s_mean"] = float(np.std(r.mean_draws))
            row["flag_beta_rs"] = pricing.flag(m_hat, row["s_mean"])
            if row["cov_points_den"] > 0:
                lo, hi = np.percentile(r.mean_draws, [2.5, 97.5])
                row["cov_mean"] = bool(lo <= m_true <= hi)
    if method in ("B1", "B1-L"):
        row["b1_duplicate_rate"] = o.duplicate_rate(select_b1(len(case["s"]), k))
    return row


def per_sample_rows(cases, plan, models, pricing, log=print):
    main_model, rt_model = models
    rows = []
    start = time.perf_counter()
    for i, case in enumerate(cases, 1):
        for rho, k in grid(case, plan):
            for method in plan["methods"]:
                if method in GP_METHODS:
                    rows.append(evaluate(case, method, rho, k, main_model, plan["draws"], pricing,
                                         case["flags"] - {"RT"}))
                    if "RT" in case["flags"]:
                        rows.append(evaluate(case, method, rho, k, rt_model, plan["draws"], pricing, {"RT"}))
                else:
                    rows.append(evaluate(case, method, rho, k, None, 0, pricing, case["flags"]))
        if i % 200 == 0 or i == len(cases):
            log(f"  {i}/{len(cases)} samples ({time.perf_counter() - start:.0f}s)")
    return rows


# ----------------------------------------------------------------------------------------------------------
# aggregation
# ----------------------------------------------------------------------------------------------------------

def select(rows, subset, method, rho=None, k=None):
    """Rows of one subset and method at a rho row (rho given) or a k_abs row (k given)."""
    if rho is not None:
        return [r for r in rows if subset in r["flags"] and r["method"] == method and r["rho"] == rho]
    return [r for r in rows if subset in r["flags"] and r["method"] == method and r["rho"] is None and r["k"] == k]


def by_week(rows, key):
    out = {}
    for r in rows:
        out.setdefault(r["iso_week"], []).append(r[key])
    return out


def mae_ci(rows, boot):
    if not rows:
        return None
    return week_bootstrap_ci(by_week(rows, "abs_err"), B=boot["B"], seed=boot["seed"])


def rate(values):
    values = [v for v in values if v is not None]
    return float(np.mean(values)) if values else None


def saving_vs_b1(cases, plan, main_model):
    """ρ grid 0.05..1.00 on MAIN without draws: 1 − ρ_method / ρ_B1, where ρ_X is the smallest ρ whose MAE is at
    most B1's MAE at ρ = 1.0. None when a method never gets there."""
    step = plan["saving_rho_grid_step"]
    rhos = [round(step * i, 2) for i in range(1, int(round(1 / step)) + 1)]
    main = [c for c in cases if "MAIN" in c["flags"]]
    if not main:
        return {m: None for m in plan["methods"]}, rhos
    mae = {}
    for method in plan["methods"]:
        model = main_model if method in GP_METHODS else None
        mae[method] = [float(np.mean([abs(float(np.mean(run(method, c["oracle"], c["s"], c["t"],
                                                             budget(c["oracle"].U, rho), model=model).y_hat))
                                          - float(np.mean(c["y"]))) for c in main]))
                       for rho in rhos]
    target = mae["B1"][-1]
    first = {m: next((rho for rho, e in zip(rhos, mae[m]) if e <= target), None) for m in plan["methods"]}
    rho_b1 = first["B1"]
    return {m: (None if first[m] is None else 1 - first[m] / rho_b1) for m in plan["methods"]}, rhos


def f1_tables(rows, plan):
    boot = plan["bootstrap"]
    curve, kabs = [], []
    for subset in plan["subsets"]:
        for method in plan["methods"]:
            for rho in plan["rhos"]:
                chosen = select(rows, subset, method, rho=rho)
                if chosen:
                    mae, lo, hi = mae_ci(chosen, boot)
                    curve.append({"subset": subset, "method": method, "rho": rho, "n": len(chosen),
                                  "mae": mae, "ci_lo": lo, "ci_hi": hi})
            for k in plan["k_abs"]:
                chosen = select(rows, subset, method, k=k)
                if chosen:
                    mae, lo, hi = mae_ci(chosen, boot)
                    kabs.append({"subset": subset, "method": method, "k": k, "n": len(chosen),
                                 "mae": mae, "ci_lo": lo, "ci_hi": hi})
    return curve, kabs


def t1_table(rows, plan, saving):
    boot = plan["bootstrap"]
    out = []
    for subset in plan["subsets"]:
        for method in plan["methods"]:
            at = {rho: select(rows, subset, method, rho=rho) for rho in (0.25, 0.5, 0.75)}
            if not at[0.5]:
                continue
            _, lo, hi = mae_ci(at[0.5], boot)
            out.append({
                "subset": subset, "method": method, "n": len(at[0.5]),
                "mae_rho25": rate([r["abs_err"] for r in at[0.25]]),
                "mae_rho50": rate([r["abs_err"] for r in at[0.5]]),
                "mae_rho75": rate([r["abs_err"] for r in at[0.75]]),
                "ci50_lo": lo, "ci50_hi": hi,
                "max_hit_rho50": rate([r["max_hit"] for r in at[0.5]]),
                "agree_rho50": rate([r["flag_beta_r"] == r["flag_true"] for r in at[0.5]]),
                "saving_vs_B1": saving[method] if subset == "MAIN" else None,
            })
    return out


def uncertain_rows(rows, method, rho):
    """MAIN rows of a GP method that leave something unobserved (ρ = 1.0 usually does not)."""
    return [r for r in select(rows, "MAIN", method, rho=rho) if r["cov_points_den"] and r["s_mean"] is not None]


def f2_tables(rows, plan):
    coverage, bins, spear = [], [], []
    for method in GP_METHODS:
        for rho in plan["rhos"]:
            chosen = uncertain_rows(rows, method, rho)
            n = len(chosen)
            coverage.append({
                "method": method, "rho": rho, "n": n,
                "cov_points": (sum(r["cov_points_num"] for r in chosen) / sum(r["cov_points_den"] for r in chosen))
                if n else None,
                "cov_mean": rate([r["cov_mean"] for r in chosen]),
            })
            s = [r["s_mean"] for r in chosen]
            spear.append({"method": method, "rho": rho, "n": n,
                          "spearman": float(spearman(s, [r["abs_err"] for r in chosen]))
                          if n >= 3 and np.ptp(s) > 0 else None})
            if n >= plan["uncertainty_bins"]:
                ordered = sorted(chosen, key=lambda r: (r["s_mean"], r["sample_id"]))
                for b, part in enumerate(np.array_split(np.arange(n), plan["uncertainty_bins"]), 1):
                    group = [ordered[i] for i in part]
                    bins.append({"method": method, "rho": rho, "bin": b, "s_lo": group[0]["s_mean"],
                                 "s_hi": group[-1]["s_mean"], "n": len(group),
                                 "mean_abs_err": rate([r["abs_err"] for r in group])})
    return coverage, bins, spear


def flag_rates(pred, true):
    n = len(true)
    return {"n": n,
            "agree": rate([p == t for p, t in zip(pred, true)]),
            "over_rate": rate([p and not t for p, t in zip(pred, true)]),
            "under_rate": rate([t and not p for p, t in zip(pred, true)])}


def beta_compare(rows, plan):
    chosen = select(rows, "ALL", "M1", rho=plan["beta_compare_rho"])
    true = [r["flag_true"] for r in chosen]
    return [{"rule": "beta_r", **flag_rates([r["flag_beta_r"] for r in chosen], true)},
            {"rule": "beta_rs", **flag_rates([r["flag_beta_rs"] for r in chosen], true)}]


def beta_sensitivity(rows, plan, pricing):
    """β(r) at each coefficient (threshold fixed at β > 1.2), every method, ALL at ρ = 0.5; rank 1 = best agree."""
    out = []
    for coef in pricing.sensitivity:
        block = []
        for method in plan["methods"]:
            chosen = select(rows, "ALL", method, rho=plan["beta_compare_rho"])
            pred = [pricing.flag(r["m_hat"], coef=coef) for r in chosen]
            true = [pricing.flag(r["m_true"], coef=coef) for r in chosen]
            block.append({"coef": coef, "method": method, **flag_rates(pred, true)})
        for row in block:
            row["rank"] = None if row["agree"] is None else \
                1 + sum(o["agree"] is not None and o["agree"] > row["agree"] for o in block)
        out += block
    return out


def stats_tests(rows, plan):
    boot = plan["bootstrap"]
    out = []
    for a, b in plan["pairs"]:
        for rho in plan["pair_rhos"]:
            ra = {r["sample_id"]: r for r in select(rows, "MAIN", a, rho=rho)}
            rb = {r["sample_id"]: r for r in select(rows, "MAIN", b, rho=rho)}
            ids = sorted(set(ra) & set(rb))
            row = {"a": a, "b": b, "rho": rho, "n": len(ids), "mean_diff": None, "ci_lo": None, "ci_hi": None,
                   "median_diff": None, "p": None}
            if ids:
                diffs = {}
                for i in ids:
                    diffs.setdefault(ra[i]["iso_week"], []).append(ra[i]["abs_err"] - rb[i]["abs_err"])
                row["mean_diff"], row["ci_lo"], row["ci_hi"] = week_bootstrap_ci(diffs, B=boot["B"], seed=boot["seed"])
                _, row["median_diff"], row["p"] = wilcoxon_pair([ra[i]["abs_err"] for i in ids],
                                                                [rb[i]["abs_err"] for i in ids])
            out.append(row)
    tested = [r for r in out if r["p"] is not None]
    for r, adj in zip(tested, holm([r["p"] for r in tested])):
        r["p_holm"] = adj
    for r in out:
        r.setdefault("p_holm", None)
        r["significant"] = None if r["p_holm"] is None else r["p_holm"] < plan["alpha"]
    return out


def b1_duplicate(rows, plan):
    out = []
    for rho in plan["rhos"]:
        chosen = select(rows, "MAIN", "B1", rho=rho)
        out.append({"rho": rho, "n": len(chosen), "mean_duplicate_rate": rate([r["b1_duplicate_rate"] for r in chosen])})
    return out


# ----------------------------------------------------------------------------------------------------------
# output
# ----------------------------------------------------------------------------------------------------------

def fmt(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    if isinstance(v, (bool, np.bool_)):
        return "1" if v else "0"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, float):
        return f"{v:.6f}"
    return str(v)


def fmt_row(row, columns, keep=("rho", "coef")):
    """Grid values (rho, coef) keep their short form, e.g. 0.25 and 1.0."""
    return [str(row[c]) if c in keep and row[c] is not None else fmt(row[c]) for c in columns]


def write_csv(path, columns, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(columns)
        for row in rows:
            w.writerow(fmt_row(row, columns))


def write_per_sample(path, rows, subsets):
    """gzip with mtime 0, so the same rows give the same bytes."""
    with open(path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz, \
            io.TextIOWrapper(gz, encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(PER_SAMPLE_COLUMNS)
        for r in rows:
            out = dict(r)
            out["subset_flags"] = "|".join(s for s in subsets if s in r["flags"])
            w.writerow(fmt_row(out, PER_SAMPLE_COLUMNS))


def summary(cases, rows, t1, coverage, dup, saving):
    def t1_mae(method):
        return next((r["mae_rho50"] for r in t1 if r["subset"] == "MAIN" and r["method"] == method), None)
    main = [c for c in cases if "MAIN" in c["flags"]]
    return {
        "n_test_main": len(main),
        "n_holdout_main": sum("HOLDOUT" in c["flags"] for c in cases),
        "n_weeks_main": len({c["week"] for c in main}),
        "headline": {
            "mae_rho50": {m: t1_mae(m) for m in HEADLINE_METHODS},
            "saving_vs_B1": {m: saving.get(m) for m in HEADLINE_METHODS},
            "b1_duplicate_rate_rho100": next((r["mean_duplicate_rate"] for r in dup if r["rho"] == 1.0), None),
            "m1_cov_points_rho50": next((r["cov_points"] for r in coverage if r["method"] == "M1" and r["rho"] == 0.5),
                                        None),
        },
    }


def compute(cases, plan, models, pricing, results_dir, log=print):
    rows = per_sample_rows(cases, plan, models, pricing, log)
    write_per_sample(os.path.join(results_dir, "test_per_sample.csv.gz"), rows, plan["subsets"])
    log("  saving grid (MAIN, draws 0)")
    saving, _ = saving_vs_b1(cases, plan, models[0])
    curve, kabs = f1_tables(rows, plan)
    t1 = t1_table(rows, plan, saving)
    coverage, bins, spear = f2_tables(rows, plan)
    dup = b1_duplicate(rows, plan)
    tables = {
        "F1_curve.csv": curve, "F1_kabs.csv": kabs, "T1_table.csv": t1,
        "F2_coverage.csv": coverage, "F2_uncertainty_bins.csv": bins, "F2_spearman.csv": spear,
        "F2_beta_compare.csv": beta_compare(rows, plan),
        "T2_beta_sensitivity.csv": beta_sensitivity(rows, plan, pricing),
        "stats_tests.csv": stats_tests(rows, plan), "B1_duplicate.csv": dup,
    }
    for name, table in tables.items():
        write_csv(os.path.join(results_dir, name), COLUMNS[name], table)
    with open(os.path.join(results_dir, "summary.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary(cases, rows, t1, coverage, dup, saving), f, indent=2)
        f.write("\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--confirm-open-test", action="store_true", help="required: opens the test split, once")
    ap.add_argument("--data-dir", default=None, help="default: PartB/data (anything else = test mode)")
    ap.add_argument("--results-dir", default=None, help="default: ../results/model_a (anything else = test mode)")
    args = ap.parse_args(argv)
    data_dir = args.data_dir or DEFAULT_DATA_DIR
    results_dir = args.results_dir or DEFAULT_RESULTS_DIR
    test_mode = is_test_mode(data_dir, results_dir)

    reason = preflight(args.confirm_open_test, results_dir, test_mode)
    if reason:
        print(f"중단: {reason}", file=sys.stderr)
        return 2
    if test_mode:
        print("테스트 모드: git·SHA 검사를 건너뜁니다", flush=True)
    write_opened(results_dir)
    print(f"wrote {os.path.join(results_dir, OPENED_NAME)}", flush=True)

    start = time.perf_counter()
    plan = load_json(FROZEN_PATH)
    pricing = Pricing(load_json(PRICING_PATH))
    models = load_models()
    cases = load_cases(data_dir)
    print(f"{len(cases)} samples ({sum('MAIN' in c['flags'] for c in cases)} MAIN, "
          f"{sum('HOLDOUT' in c['flags'] for c in cases)} HOLDOUT, {sum('RT' in c['flags'] for c in cases)} RT)",
          flush=True)
    compute(cases, plan, models, pricing, results_dir, log=lambda m: print(m, flush=True))
    print(f"done in {time.perf_counter() - start:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
