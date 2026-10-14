"""Post-hoc placement comparison (paper-revision-v1 X1): where does M2's gain come from?

The test split was opened on 2026-10-08 (card B6). This is a post-hoc analysis: it never runs
training.final_eval and only reads results/model_a/ (to check that B1, M1 and M2 are reproduced exactly).
The compared rules, statistics and decision rule were fixed in docs/plan/paper-revision-v1.md §3 before
this script was run.

Every rule queries k = budget(U, rho) cells and fills the rest with the same GP as M2 (frozen main model,
no draws), so only the queried cells differ. H-R, H-N, H-D and H-S start from M2's anchor
select_b2(order, ceil(k/2)); H-C and H-P have no anchor. Ties always go to the cell that appears first.

Run from PartB/ (reads parquet, so inside Docker on this PC):
    python -m training.posthoc_placement [--limit N] [--out-dir DIR]
Writes <out-dir>/placement_per_sample.csv.gz, placement_mae.csv, placement_saving.csv, placement_tests.csv,
placement_profile.csv and summary.json (default out-dir: ../results/posthoc/model_a). If the recomputed
B1/M1/M2 errors differ from test_per_sample.csv.gz by more than 1e-6, nothing is written and the exit code is 3.
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
import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402

from training import final_eval  # noqa: E402
from weather.methods import gp_fill, run, select_m2  # noqa: E402
from weather.selection import budget, select_b1, select_b2  # noqa: E402
from weather.stats import holm, week_bootstrap_ci, wilcoxon_pair  # noqa: E402

DEFAULT_OUT_DIR = os.path.join(final_eval.ROOT, "results", "posthoc", "model_a")
SUBSETS = ("MAIN", "HOLDOUT")
RHOS = (0.25, 0.5, 0.75)
BASE_METHODS = ("B1", "M1", "M2")
RULE_NAMES = ("H-C", "H-P", "H-R", "H-N", "H-D", "H-S")
METHODS = BASE_METHODS + RULE_NAMES
SAVING_METHODS = ("B1", "M2") + RULE_NAMES
SAVING_RHOS = tuple(round(0.05 * i, 2) for i in range(1, 21))
PAIRS = [("M2", r) for r in RULE_NAMES] + [("M2", "B1"), ("H-C", "M1")]
BOOT_B, BOOT_SEED, ALPHA = 2000, 42, 0.05
TOL = 1e-6
SEED = 42

PER_SAMPLE_COLUMNS = ("sample_id", "subset", "iso_week", "U", "P", "rho", "k", "method", "cells", "same_as_m2",
                      "m_true", "m_hat", "abs_err")
COLUMNS = {
    "placement_mae.csv": ("subset", "method", "rho", "n", "mae", "ci_lo", "ci_hi"),
    "placement_saving.csv": ("method", "first_rho", "saving_vs_B1", "target_mae"),
    "placement_tests.csv": ("a", "b", "rho", "n", "mean_diff", "ci_lo", "ci_hi", "median_diff", "p", "p_holm",
                            "significant"),
    "placement_profile.csv": ("key", "value"),
}


# ----------------------------------------------------------------------------------------------------------
# placement rules: each returns k distinct cell ids and never looks at y
# ----------------------------------------------------------------------------------------------------------

def anchor(order, k):
    """M2's starting cells."""
    return list(select_b2(order, math.ceil(k / 2)))


def select_hc(order, k):
    """Cell-centred: the centre of each of k equal blocks of the cell order (no end cells forced)."""
    U = len(order)
    return [order[int(np.floor((i + 0.5) * U / k))] for i in range(k)]


def select_hp(oracle, k):
    """Point-centred: the cell of the centre point of each of k equal blocks of the route points; a cell that is
    already chosen is replaced by the unchosen cell with a point closest (in index) to that centre point."""
    P = len(oracle.cell)
    chosen = []
    for i in range(k):
        t = int(np.floor((i + 0.5) * P / k))
        c = oracle.cell[t].item()
        if c not in chosen:
            chosen.append(c)
            continue
        rest = [c for c in oracle.order if c not in chosen]
        gaps = [int(np.min(np.abs(oracle.points_of(c) - t))) for c in rest]
        chosen.append(rest[int(np.argmin(gaps))])                      # argmin keeps the first on ties
    return chosen


def select_hr(oracle, k, sample_id):
    """Anchor, then the rest drawn without replacement (control: is the variance step better than chance?)."""
    chosen = anchor(oracle.order, k)
    rest = [c for c in oracle.order if c not in chosen]
    rng = np.random.default_rng([SEED, int(sample_id), int(k)])
    picks = sorted(rng.choice(len(rest), size=k - len(chosen), replace=False).tolist())
    return chosen + [rest[i] for i in picks]


def distances(oracle, s, chosen):
    """Route distance from every point to the nearest point of a chosen cell."""
    obs_s = s[np.isin(oracle.cell, chosen)]
    return np.min(np.abs(s[:, None] - obs_s[None, :]), axis=1)


def greedy(oracle, s, k, score):
    """Anchor, then one at a time the unqueried cell with the largest score(points of c, d)."""
    chosen = anchor(oracle.order, k)
    while len(chosen) < k:
        d = distances(oracle, s, chosen)
        rest = [c for c in oracle.order if c not in chosen]
        scores = [score(oracle.points_of(c), d) for c in rest]
        chosen.append(rest[int(np.argmax(scores))])                    # argmax keeps the first on ties
    return chosen


RULES = {
    "H-C": lambda oracle, s, k, sid: select_hc(oracle.order, k),
    "H-P": lambda oracle, s, k, sid: select_hp(oracle, k),
    "H-R": lambda oracle, s, k, sid: select_hr(oracle, k, sid),
    "H-N": lambda oracle, s, k, sid: greedy(oracle, s, k, lambda pts, d: len(pts)),
    "H-D": lambda oracle, s, k, sid: greedy(oracle, s, k, lambda pts, d: float(np.min(d[pts]))),
    "H-S": lambda oracle, s, k, sid: greedy(oracle, s, k, lambda pts, d: float(np.sum(d[pts]))),
}


def predict(method, case, k, model, with_cells=True):
    """(cells or None, m_hat) of one method at budget k, with the same m_hat as final_eval.evaluate.
    B1, M1 and M2 go through weather.methods.run itself, so they are the frozen methods, not copies."""
    o, s, t = case["oracle"], case["s"], case["t"]
    sid = int(case["sample"]["sample_id"])
    if method in RULES:
        cells = RULES[method](o, s, k, sid)
        idx, y, calls = o.reveal_cells(cells)
        r = gp_fill(s, t, idx, y, model, sample_id=sid, draws=0, calls=calls)
        return cells, float(np.mean(r.y_hat))
    gp = method in ("M1", "M2")
    r = run(method, o, s, t, k, model=model if gp else None, sample_id=sid, draws=0)
    cells = None
    if with_cells and method == "M1":
        cells = list(select_b2(o.order, k))
    elif with_cells and method == "M2":
        cells = list(select_m2(o, s, t, k, model))
    return cells, float(np.mean(r.y_hat))


# ----------------------------------------------------------------------------------------------------------
# computation
# ----------------------------------------------------------------------------------------------------------

def subset_of(case):
    return next((x for x in SUBSETS if x in case["flags"]), None)


def per_sample_rows(cases, model, log=print):
    rows = []
    start = time.perf_counter()
    for i, case in enumerate(cases, 1):
        U, m_true = case["oracle"].U, float(np.mean(case["y"]))
        for rho in RHOS:
            k = budget(U, rho)
            block = []
            for method in METHODS:
                cells, m_hat = predict(method, case, k, model)
                block.append({"sample_id": int(case["sample"]["sample_id"]), "subset": subset_of(case),
                              "iso_week": case["week"], "U": U, "P": len(case["s"]), "rho": rho, "k": k,
                              "method": method, "cell_list": cells, "m_true": m_true, "m_hat": m_hat,
                              "abs_err": abs(m_hat - m_true)})
            m2 = set(next(r["cell_list"] for r in block if r["method"] == "M2"))
            for r in block:
                r["cells"] = None if r["cell_list"] is None else ";".join(str(c) for c in r["cell_list"])
                r["same_as_m2"] = None if r["cell_list"] is None else set(r["cell_list"]) == m2
            rows += block
        if i % 100 == 0 or i == len(cases):
            log(f"  {i}/{len(cases)} samples ({time.perf_counter() - start:.0f}s)")
    return rows


def read_frozen(frozen_dir, sample_ids):
    """{(sample_id, method, rho string): abs_err} of the frozen B1/M1/M2 main-model rows for MAIN or HOLDOUT."""
    out = {}
    with gzip.open(os.path.join(frozen_dir, "test_per_sample.csv.gz"), "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["method"] not in BASE_METHODS or r["rho"] not in ("0.25", "0.5", "0.75"):
                continue
            flags = r["subset_flags"].split("|")
            if not any(x in flags for x in SUBSETS) or int(r["sample_id"]) not in sample_ids:
                continue
            out[(int(r["sample_id"]), r["method"], r["rho"])] = float(r["abs_err"])
    return out


def reproduction(rows, frozen):
    """(checked rows, max |difference|, mismatches) of the recomputed B1/M1/M2 errors."""
    checked, worst, bad = 0, 0.0, []
    for r in rows:
        if r["method"] not in BASE_METHODS:
            continue
        key = (r["sample_id"], r["method"], str(r["rho"]))
        if key not in frozen:
            bad.append((key, "missing"))
            continue
        diff = abs(r["abs_err"] - frozen[key])
        checked, worst = checked + 1, max(worst, diff)
        if diff > TOL:
            bad.append((key, diff))
    return checked, worst, bad


def pick(rows, subset, method, rho):
    return [r for r in rows if r["subset"] == subset and r["method"] == method and r["rho"] == rho]


def by_week(rows, key):
    out = {}
    for r in rows:
        out.setdefault(r["iso_week"], []).append(r[key])
    return out


def mae_table(rows):
    out = []
    for subset in SUBSETS:
        for method in METHODS:
            for rho in RHOS:
                chosen = pick(rows, subset, method, rho)
                row = {"subset": subset, "method": method, "rho": rho, "n": len(chosen),
                       "mae": None, "ci_lo": None, "ci_hi": None}
                if chosen:
                    row["mae"], row["ci_lo"], row["ci_hi"] = week_bootstrap_ci(by_week(chosen, "abs_err"),
                                                                               B=BOOT_B, seed=BOOT_SEED)
                out.append(row)
    return out


def saving_table(cases, model, log=print):
    """final_eval.saving_vs_b1 on the same grid, for B1, M2 and the rules (MAIN, no draws)."""
    main = [c for c in cases if "MAIN" in c["flags"]]
    if not main:
        return [{"method": m, "first_rho": None, "saving_vs_B1": None, "target_mae": None} for m in SAVING_METHODS]
    mae = {}
    for method in SAVING_METHODS:
        mae[method] = [float(np.mean([abs(predict(method, c, budget(c["oracle"].U, rho), model, with_cells=False)[1]
                                          - float(np.mean(c["y"]))) for c in main]))
                       for rho in SAVING_RHOS]
        log(f"  saving grid {method}")
    target = mae["B1"][-1]
    first = {m: next((rho for rho, e in zip(SAVING_RHOS, mae[m]) if e <= target), None) for m in SAVING_METHODS}
    return [{"method": m, "first_rho": first[m], "target_mae": target,
             "saving_vs_B1": None if first[m] is None else 1 - first[m] / first["B1"]} for m in SAVING_METHODS]


def tests_table(rows):
    out = []
    for a, b in PAIRS:
        for rho in RHOS:
            ra = {r["sample_id"]: r for r in pick(rows, "MAIN", a, rho)}
            rb = {r["sample_id"]: r for r in pick(rows, "MAIN", b, rho)}
            ids = sorted(set(ra) & set(rb))
            row = {"a": a, "b": b, "rho": rho, "n": len(ids), "mean_diff": None, "ci_lo": None, "ci_hi": None,
                   "median_diff": None, "p": None}
            if ids:
                diffs = {}
                for i in ids:
                    diffs.setdefault(ra[i]["iso_week"], []).append(ra[i]["abs_err"] - rb[i]["abs_err"])
                row["mean_diff"], row["ci_lo"], row["ci_hi"] = week_bootstrap_ci(diffs, B=BOOT_B, seed=BOOT_SEED)
                _, row["median_diff"], row["p"] = wilcoxon_pair([ra[i]["abs_err"] for i in ids],
                                                                [rb[i]["abs_err"] for i in ids])
            out.append(row)
    tested = [r for r in out if r["p"] is not None]
    for r, adj in zip(tested, holm([r["p"] for r in tested])):
        r["p_holm"] = adj
    for r in out:
        r.setdefault("p_holm", None)
        r["significant"] = None if r["p_holm"] is None else r["p_holm"] < ALPHA
    return out


def profile_table(cases, rows):
    main = [c for c in cases if "MAIN" in c["flags"]]
    prof = [("main_n", len(main)), ("holdout_n", sum("HOLDOUT" in c["flags"] for c in cases))]
    if not main:
        return [{"key": k, "value": v} for k, v in prof]
    Us = np.array([c["oracle"].U for c in main])
    prof += [("main_U_mean", float(Us.mean())), ("main_U_median", float(np.median(Us)))]
    prof += [(f"main_U_count_{u}", int((Us == u).sum())) for u in sorted(set(Us.tolist()))]
    for rho in RHOS:
        ks = np.array([budget(u, rho) for u in Us])
        prof += [(f"main_k_count_rho{rho}_{k}", int((ks == k).sum())) for k in sorted(set(ks.tolist()))]
    picks = np.array([budget(u, 0.5) - math.ceil(budget(u, 0.5) / 2) for u in Us])
    prof += [(f"main_var_picks_count_rho0.5_{j}", int((picks == j).sum())) for j in sorted(set(picks.tolist()))]
    for rho in RHOS:
        for rule in RULE_NAMES:
            chosen = pick(rows, "MAIN", rule, rho)
            prof.append((f"same_as_m2_share_rho{rho}_{rule}", float(np.mean([r["same_as_m2"] for r in chosen]))))
    end_pts, inner_pts, dup, missed = [], [], [], []
    for c in main:
        o = c["oracle"]
        counts = [len(o.points_of(x)) for x in o.order]
        end_pts.append((counts[0] + counts[-1]) / 2)
        inner_pts.append(float(np.mean(counts[1:-1])))
        idx = select_b1(len(c["s"]), o.U)
        dup.append(o.duplicate_rate(idx))
        missed.append(1 - len(set(o.cell[np.asarray(idx, dtype=int)].tolist())) / o.U)
    prof += [("endcell_points_mean", float(np.mean(end_pts))), ("innercell_points_mean", float(np.mean(inner_pts))),
             ("b1_rho1_duplicate_rate_mean", float(np.mean(dup))),
             ("b1_rho1_missed_cell_share_mean", float(np.mean(missed)))]
    return [{"key": k, "value": v} for k, v in prof]


# ----------------------------------------------------------------------------------------------------------
# output
# ----------------------------------------------------------------------------------------------------------

def write_per_sample(path, rows):
    """gzip with mtime 0, so the same rows give the same bytes."""
    with open(path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz, \
            io.TextIOWrapper(gz, encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(PER_SAMPLE_COLUMNS)
        for r in rows:
            w.writerow(final_eval.fmt_row(r, PER_SAMPLE_COLUMNS))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default=final_eval.DEFAULT_DATA_DIR)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--frozen-dir", default=final_eval.DEFAULT_RESULTS_DIR,
                    help="where test_per_sample.csv.gz of the one-time opening is (read only)")
    ap.add_argument("--limit", type=int, default=None, help="first N MAIN/HOLDOUT samples only (smoke run)")
    args = ap.parse_args(argv)

    start = time.perf_counter()
    model, _ = final_eval.load_models()
    cases = [c for c in final_eval.load_cases(args.data_dir) if subset_of(c)]
    if args.limit is not None:
        cases = cases[:args.limit]
    print(f"{len(cases)} samples ({sum('MAIN' in c['flags'] for c in cases)} MAIN, "
          f"{sum('HOLDOUT' in c['flags'] for c in cases)} HOLDOUT)", flush=True)
    log = lambda m: print(m, flush=True)  # noqa: E731

    rows = per_sample_rows(cases, model, log)
    frozen = read_frozen(args.frozen_dir, {int(c["sample"]["sample_id"]) for c in cases})
    checked, worst, bad = reproduction(rows, frozen)
    if bad:
        print(f"중단: B1/M1/M2 재현 실패 {len(bad)}건, 예: {bad[:3]}", file=sys.stderr)
        return 3
    print(f"reproduction ok: {checked} rows, max |diff| = {worst:.2e}", flush=True)

    saving = saving_table(cases, model, log)
    tables = {"placement_mae.csv": mae_table(rows), "placement_saving.csv": saving,
              "placement_tests.csv": tests_table(rows), "placement_profile.csv": profile_table(cases, rows)}
    os.makedirs(args.out_dir, exist_ok=True)
    write_per_sample(os.path.join(args.out_dir, "placement_per_sample.csv.gz"), rows)
    for name, table in tables.items():
        final_eval.write_csv(os.path.join(args.out_dir, name), COLUMNS[name], table)
    by = {r["method"]: r for r in saving}
    record = {
        "utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_head": (final_eval.git("rev-parse", "HEAD") or "").strip() or None,
        "n_main": sum("MAIN" in c["flags"] for c in cases), "n_holdout": sum("HOLDOUT" in c["flags"] for c in cases),
        "reproduction_checked_rows": checked, "reproduction_max_abs_diff": worst,
        "m2_saving": by["M2"]["saving_vs_B1"], "b1_first_rho": by["B1"]["first_rho"],
    }
    with open(os.path.join(args.out_dir, "summary.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(record, f, indent=2)
        f.write("\n")
    print(f"done in {time.perf_counter() - start:.0f}s -> {args.out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
