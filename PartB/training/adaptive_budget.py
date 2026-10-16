"""GP-uncertainty adaptive budget, pre-registered in docs/adaptive-budget.md (committed before this was run).

A: query the point-centre cell; stop if all its points are 0; otherwise add the unqueried cell with the largest
summed posterior variance (M2's score) one at a time and stop once the GP route-mean sd (200 draws) < tau.
B: fixed point-centre rule at k = budget(U, 0.5). C: A's order and dry stop, but stopping from observed cell
means only (range < d or mean < t). tau and C are chosen on the validation split to match B's mean calls there.
Primary tests: A-B and A-C on the temporal set (Wilcoxon, Holm over 2); MAIN test is supporting (direction,
calls). Also reports an error-calls frontier, surcharge kappa and the wet-first-cell subset. Run once.

    python -m training.adaptive_budget     # from PartB/ (Docker) -> results/adaptive_budget/
"""
import csv
import gzip
import json
import os
import sys
from collections import defaultdict

import numpy as np

from training import final_eval
from training import temporal_check as tc
from training.posthoc_placement import select_hp
from weather import data
from weather.methods import gp_fill
from weather.oracle import RouteOracle
from weather.selection import budget
from weather.stats import holm, week_bootstrap_ci, wilcoxon_pair

DRAWS = 200
TAUS = [round(0.005 * i, 3) for i in range(1, 61)]
DS = [round(0.01 * i, 2) for i in range(1, 101)]
TS = [round(0.01 * i, 2) for i in range(1, 201)]
CALL_SLACK = 1.05
MARGIN = 0.97                 # tune to 97% of B's validation calls (room for shift on the test sets)
RHOS = (0.25, 0.5, 0.75)
FLAG_MM = 4 / 3               # beta(r, 0) > 1.2  <=>  r > 4/3 mm/h (c_beta = 0.15)
ALPHA = 0.05
BOOT_B, BOOT_SEED = 2000, 42
OUT = os.path.join(final_eval.ROOT, "results", "adaptive_budget")


def trajectory(case, model):
    """Steps of A/C's shared order: [(calls, m_hat, sd, cell_means)]; a dry first cell ends it after step 1."""
    o, s, t = case["oracle"], case["s"], case["t"]
    sid = int(case["sample"]["sample_id"])
    chosen = list(select_hp(o, 1))
    steps = []
    while True:
        idx, yy, calls = o.reveal_cells(chosen)
        res = gp_fill(s, t, idx, yy, model, sample_id=sid, draws=DRAWS, calls=calls)
        cm = [float(np.mean(o.y[o.points_of(c)])) for c in chosen]
        steps.append((calls, float(np.mean(res.y_hat)), float(np.std(res.mean_draws)), cm))
        rest = [c for c in o.order if c not in chosen]
        if (len(chosen) == 1 and float(np.max(yy)) <= 0.0) or not rest:
            return steps
        score = [float(np.sum(res.std_z[o.points_of(c)] ** 2)) for c in rest]
        chosen.append(rest[int(np.argmax(score))])


def stop_at(steps, rule):
    """First step where rule(step) holds (a dry first cell or the last step always stops)."""
    for i, st in enumerate(steps):
        if i == len(steps) - 1 or rule(st) or (i == 0 and len(steps) == 1):
            return st
    return steps[-1]


RULES = {
    "A": lambda tau: (lambda st: st[2] < tau),
    "C-range": lambda d: (lambda st: len(st[3]) > 1 and max(st[3]) - min(st[3]) < d),
    "C-mean": lambda t: (lambda st: float(np.mean(st[3])) < t),
}


def fixed_b(case, model, rho):
    o = case["oracle"]
    cells = select_hp(o, budget(o.U, rho))
    idx, yy, calls = o.reveal_cells(cells)
    res = gp_fill(case["s"], case["t"], idx, yy, model, sample_id=int(case["sample"]["sample_id"]), calls=calls)
    return calls, float(np.mean(res.y_hat))


def prepare(cases, model, log, name):
    out = []
    for n, c in enumerate(cases, 1):
        bs = {rho: fixed_b(c, model, rho) for rho in RHOS}
        out.append({"case": c, "m": float(np.mean(c["y"])), "traj": trajectory(c, model), "B": bs[0.5], "Bs": bs})
        if n % 200 == 0 or n == len(cases):
            log(f"  {name}: {n}/{len(cases)}")
    return out


def summarise(prepped, rule):
    calls = [stop_at(p["traj"], rule)[0] for p in prepped]
    err = [abs(stop_at(p["traj"], rule)[1] - p["m"]) for p in prepped]
    return float(np.mean(calls)), float(np.mean(err))


def tune(val, rho=0.5):
    target = MARGIN * float(np.mean([p["Bs"][rho][0] for p in val]))
    a = [(tau, *summarise(val, RULES["A"](tau))) for tau in TAUS]
    ok = [x for x in a if x[1] <= target]
    # descriptive budgets only: if nothing reaches the target, take the fewest-calls setting (flagged)
    tau = max(ok, key=lambda x: (x[1], -x[0]))[0] if ok else min(a, key=lambda x: (x[1], x[0]))[0]
    best, over = {}, not ok
    for fam, grid in (("C-range", DS), ("C-mean", TS)):
        cand = [(g, *summarise(val, RULES[fam](g))) for g in grid]
        under = [x for x in cand if x[1] <= target]
        best[fam] = min(under, key=lambda x: (x[2], x[0])) if under else min(cand, key=lambda x: (x[1], x[2]))
        over = over or not under
    under_fams = [f for f in best if best[f][1] <= target] or list(best)
    fam = min(under_fams, key=lambda f: best[f][2])
    return {"target_calls": target, "tau": tau, "A_val": [x for x in a if x[0] == tau][0][1:],
            "C_family": fam, "C_param": best[fam][0], "C_val": best[fam][1:], "C_candidates": best,
            "over_target": over}


def per_sample(prepped, choice, label):
    a_rule, c_rule = RULES["A"](choice["tau"]), RULES[choice["C_family"]](choice["C_param"])
    rows = []
    for p in prepped:
        c = p["case"]
        a, cc = stop_at(p["traj"], a_rule), stop_at(p["traj"], c_rule)
        rows.append({"set": label, "sample_id": int(c["sample"]["sample_id"]), "iso_week": c["week"],
                     "route": f'{c["sample"]["route_set"]}-{c["sample"]["route_id"]}', "U": c["oracle"].U,
                     "m_true": p["m"], "A_calls": a[0], "A_err": abs(a[1] - p["m"]), "B_calls": p["B"][0],
                     "B_err": abs(p["B"][1] - p["m"]), "C_calls": cc[0], "C_err": abs(cc[1] - p["m"])})
    return rows


def test(rows, other):
    diffs = defaultdict(list)
    for r in rows:
        diffs[r["iso_week"]].append(r["A_err"] - r[f"{other}_err"])
    mean, lo, hi = week_bootstrap_ci(diffs, B=BOOT_B, seed=BOOT_SEED)
    _, med, p = wilcoxon_pair([r["A_err"] for r in rows], [r[f"{other}_err"] for r in rows])
    out = {"n": len(rows), "mean_diff": mean, "ci_lo": lo, "ci_hi": hi, "median_diff": med, "p": p,
           "A_calls": float(np.mean([r["A_calls"] for r in rows])),
           f"{other}_calls": float(np.mean([r[f"{other}_calls"] for r in rows])),
           "A_mae": float(np.mean([r["A_err"] for r in rows])),
           f"{other}_mae": float(np.mean([r[f"{other}_err"] for r in rows]))}
    for key in ("route", "iso_week"):                       # robustness: cluster means
        by = defaultdict(list)
        for r in rows:
            by[r[key]].append(r["A_err"] - r[f"{other}_err"])
        means = [np.mean(v) for v in by.values()]
        out[f"p_{key}_means"] = wilcoxon_pair(means, [0.0] * len(means))[2]
    return out


def judge(tests):
    """Primary (temporal): Holm over the two, p < alpha, A better, calls ok. Supporting (MAIN): A better, calls ok."""
    primary = [r for r in tests if r["set"] == "temporal"]
    for r, adj in zip(primary, holm([r["p"] for r in primary])):
        r["p_holm"] = adj
    for r in tests:
        r["role"] = "primary" if r["set"] == "temporal" else "supporting"
        r["calls_ok"] = r["A_calls"] <= CALL_SLACK * r[f'{r["vs"]}_calls']
        r.setdefault("p_holm", None)
        sig = r["p_holm"] is not None and r["p_holm"] < ALPHA
        r["passed"] = bool(r["mean_diff"] < 0 and r["calls_ok"] and (sig or r["role"] == "supporting"))
    return all(r["passed"] for r in tests)


def kappa(pred, true):
    pred, true = np.asarray(pred), np.asarray(true)
    po = float(np.mean(pred == true))
    pe = float(np.mean(pred) * np.mean(true) + (1 - np.mean(pred)) * (1 - np.mean(true)))
    return None if pe == 1 else (po - pe) / (1 - pe)


def descriptive(val, sets, choice):
    out = {"frontier": {}, "kappa": {}, "wet_first": {}}
    for rho in RHOS:
        ch = choice if rho == 0.5 else tune(val, rho)
        a_rule, c_rule = RULES["A"](ch["tau"]), RULES[ch["C_family"]](ch["C_param"])
        out["frontier"][str(rho)] = {"tau": ch["tau"], "C": [ch["C_family"], ch["C_param"]]}
        for label, prepped in sets.items():
            out["frontier"][str(rho)][label] = {
                "A": summarise(prepped, a_rule), "C": summarise(prepped, c_rule),
                "B": (float(np.mean([p["Bs"][rho][0] for p in prepped])),
                      float(np.mean([abs(p["Bs"][rho][1] - p["m"]) for p in prepped])))}
    a_rule, c_rule = RULES["A"](choice["tau"]), RULES[choice["C_family"]](choice["C_param"])
    for label, prepped in sets.items():
        true = [p["m"] > FLAG_MM for p in prepped]
        out["kappa"][label] = {"A": kappa([stop_at(p["traj"], a_rule)[1] > FLAG_MM for p in prepped], true),
                               "B": kappa([p["B"][1] > FLAG_MM for p in prepped], true),
                               "C": kappa([stop_at(p["traj"], c_rule)[1] > FLAG_MM for p in prepped], true),
                               "flag_rate": float(np.mean(true))}
        wet = [p for p in prepped if len(p["traj"]) > 1 or p["traj"][0][3][0] > 0]
        out["wet_first"][label] = {"n": len(wet), "share": len(wet) / len(prepped),
                                   "A": summarise(wet, a_rule), "C": summarise(wet, c_rule)}
    return out


def val_cases():
    routes, samples = data.load_routes(), data.load_samples(["val"])
    out = []
    for smp in samples:
        r = routes[(smp["route_set"], smp["route_id"])]
        if r["unique_cells"] < 3 or not np.max(smp["gt_mm"]) > data.WET_MM:
            continue
        y, wk = smp["gt_mm"], data.iso_week(smp["departure_utc"])
        out.append({"sample": smp, "y": y, "oracle": RouteOracle(r["cell"], y), "s": r["s_km"], "t": r["t_min"],
                    "week": f"{wk[0]}-W{wk[1]:02d}"})
    return out


def temporal_cases():
    with open(os.path.join(data.DATA_DIR, "grid_cells.json"), encoding="utf-8") as f:
        n_cells = len(json.load(f)["cells"])
    first, precip, _ = tc.load_period(n_cells)
    offsets, stamps = tc.candidate_offsets(first)
    routes = data.load_routes()
    samples, _ = tc.draw_samples(routes, precip, offsets, stamps, np.random.default_rng(tc.SEED))
    return tc.make_cases(samples, routes)


def main():
    log = lambda m: print(m, flush=True)  # noqa: E731
    model, _ = final_eval.load_models()
    val = prepare(val_cases(), model, log, "val")
    choice = tune(val)
    log(f"tuned on validation: {json.dumps(choice)}")
    main_cases = [c for c in final_eval.load_cases(final_eval.DEFAULT_DATA_DIR) if "MAIN" in c["flags"]]
    sets = {"MAIN": prepare(main_cases, model, log, "MAIN"), "temporal": prepare(temporal_cases(), model, log, "temporal")}
    rows, tests = [], []
    for label, prepped in sets.items():
        rs = per_sample(prepped, choice, label)
        rows += rs
        for other, h in (("B", "H1"), ("C", "H2")):
            tests.append({"test": f"{h}-{'a' if label == 'MAIN' else 'b'}", "set": label, "vs": other, **test(rs, other)})
    passed = judge(tests)
    desc = descriptive(val, sets, choice)
    os.makedirs(OUT, exist_ok=True)
    with gzip.open(os.path.join(OUT, "per_sample.csv.gz"), "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(OUT, "tests.csv"), "w", encoding="utf-8", newline="") as f:
        keys = sorted({k for t in tests for k in t})
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(tests)
    summary = {"git_head": (final_eval.git("rev-parse", "HEAD") or "").strip() or None, "choice": choice,
               "tests": tests, "all_passed": passed, "descriptive": desc}
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=2, default=float)
        f.write("\n")
    for t in tests:
        log(f'{t["test"]} A vs {t["vs"]} on {t["set"]}: MAE {t["A_mae"]:.4f} vs {t[t["vs"] + "_mae"]:.4f}, '
            f'calls {t["A_calls"]:.2f} vs {t[t["vs"] + "_calls"]:.2f}, p {t["p"]:.3g}, p_holm {t["p_holm"]}, '
            f'{t["role"]} -> {"pass" if t["passed"] else "FAIL"}')
    log(f"ALL PASSED: {passed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
