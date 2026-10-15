"""Temporal hold-out check, pre-registered in docs/temporal-check.md (committed before any of this data was fetched).

Downloads the 82 cells for 2025-12-01..2026-10-14 (after every period the frozen model, its settings and the post-hoc
analysis saw), cuts wet (route, departure) samples on the existing routes, and runs the frozen methods B1, M1, M2 and
the post-hoc rule H-P exactly as training.posthoc_placement does. Two tests decide the outcome:
T-1 M2 - H-P and T-2 B1 - M2 at k/U = 0.5, two-sided Wilcoxon, Holm over the two, supported if p_holm < 0.05 and the
mean difference is positive. Run once.

Run from PartB/ (Docker, parquet):  python -m training.temporal_check
Writes results/temporal/: per_sample.csv.gz, mae.csv, tests.csv, summary.json.
"""
import csv
import datetime
import gzip
import hashlib
import json
import os
import sys
import time

import httpx
import numpy as np

from training import collect_groundtruth as cg
from training import final_eval, posthoc_placement as pp
from training.build_samples import arrival_values
from weather import data
from weather.oracle import RouteOracle
from weather.selection import budget
from weather.stats import holm, week_bootstrap_ci, wilcoxon_pair

START, END = datetime.date(2025, 12, 1), datetime.date(2026, 10, 14)
LOCAL_HOURS = range(6, 24)               # IST 06:00 .. 23:00, on the hour
IST_OFFSET_H = 5.5
PER_ROUTE = 4
SEED = 20261016
RHOS = (0.25, 0.5, 0.75)
METHODS = ("B1", "M1", "M2", "H-P")
TESTS = (("T-1", "M2", "H-P"), ("T-2", "B1", "M2"))
TEST_RHO = 0.5
BOOT_B, BOOT_SEED, ALPHA = 2000, 42, 0.05
SAMPLE_ID_BASE = 900000
OUT_DIR = os.path.join(final_eval.ROOT, "results", "temporal")


def load_period(n_cells):
    """(first UTC stamp, cells x hours precipitation with NaN for missing, SHA-256 of the raw files)."""
    folder = os.path.join(cg.RAW_DIR, cg.period_tag(START, END))
    digest = hashlib.sha256()
    series, first = [], None
    for i in range(n_cells):
        path = os.path.join(folder, f"{i:03d}.json")
        with open(path, "rb") as f:
            raw = f.read()
        digest.update(raw)
        h = json.loads(raw)["hourly"]
        t0, t1 = datetime.datetime.fromisoformat(h["time"][0]), datetime.datetime.fromisoformat(h["time"][-1])
        if len(h["time"]) != int((t1 - t0) / datetime.timedelta(hours=1)) + 1:
            raise RuntimeError(f"cell {i}: hourly series has gaps or overlaps")
        if first is None:
            first = t0
        elif t0 != first:
            raise RuntimeError(f"cell {i}: series starts at {t0}, not {first}")
        series.append([np.nan if v is None else float(v) for v in h["precipitation"]])
    return first, np.array(series), digest.hexdigest()


def candidate_offsets(first_utc):
    """Departure offsets (hours after first_utc) and their UTC times: every IST hour in LOCAL_HOURS of the period."""
    offsets, stamps = [], []
    day = START
    while day <= END:
        for h in LOCAL_HOURS:
            utc = datetime.datetime.combine(day, datetime.time(h)) - datetime.timedelta(hours=IST_OFFSET_H)
            offsets.append((utc - first_utc) / datetime.timedelta(hours=1))
            stamps.append(utc)
        day += datetime.timedelta(days=1)
    return np.array(offsets), stamps


def draw_samples(routes, precip, offsets, stamps, rng):
    """Up to PER_ROUTE wet departures per U >= 3 route, routes in (route_set, route_id) order.
    Departures whose arrival values include a missing hour are not candidates (counted)."""
    samples, skipped_missing = [], 0
    for key in sorted(routes):
        route = routes[key]
        if route["unique_cells"] < 3:
            continue
        values = arrival_values(precip, route["cell"], route["t_min"], offsets)
        complete = ~np.isnan(values).any(axis=1)
        skipped_missing += int((~complete).sum())
        wet = np.nonzero(complete & (np.nanmax(values, axis=1) > data.WET_MM))[0]
        if len(wet) == 0:
            continue
        for d in np.sort(rng.choice(wet, size=min(PER_ROUTE, len(wet)), replace=False)):
            samples.append({"route_set": key[0], "route_id": key[1], "departure_utc": stamps[d], "gt_mm": values[d]})
    return samples, skipped_missing


def make_cases(samples, routes):
    cases = []
    for i, smp in enumerate(samples):
        route = routes[(smp["route_set"], smp["route_id"])]
        year, week = data.iso_week(np.datetime64(smp["departure_utc"], "m"))
        cases.append({"sample": {**smp, "sample_id": SAMPLE_ID_BASE + i}, "route": route, "y": smp["gt_mm"],
                      "oracle": RouteOracle(route["cell"], smp["gt_mm"]), "s": route["s_km"], "t": route["t_min"],
                      "week": f"{year}-W{week:02d}"})
    return cases


def evaluate(cases, model, log=print):
    rows = []
    for n, case in enumerate(cases, 1):
        U, m_true = case["oracle"].U, float(np.mean(case["y"]))
        for rho in RHOS:
            k = budget(U, rho)
            for method in METHODS:
                _, m_hat = pp.predict(method, case, k, model, with_cells=False)
                rows.append({"sample_id": case["sample"]["sample_id"], "route_set": case["sample"]["route_set"],
                             "route_id": case["sample"]["route_id"], "iso_week": case["week"], "U": U, "rho": rho,
                             "k": k, "method": method, "m_true": m_true, "m_hat": m_hat,
                             "abs_err": abs(m_hat - m_true)})
        if n % 200 == 0 or n == len(cases):
            log(f"  {n}/{len(cases)} samples")
    return rows


def errors(rows, method, rho):
    return {r["sample_id"]: r for r in rows if r["method"] == method and r["rho"] == rho}


def mae_table(rows):
    out = []
    for rho in RHOS:
        for method in METHODS:
            sel = errors(rows, method, rho).values()
            by_week = {}
            for r in sel:
                by_week.setdefault(r["iso_week"], []).append(r["abs_err"])
            mean, lo, hi = week_bootstrap_ci(by_week, B=BOOT_B, seed=BOOT_SEED)
            out.append({"rho": rho, "method": method, "n": len(sel), "mae": mean, "ci_lo": lo, "ci_hi": hi})
    return out


def tests_table(rows):
    out = []
    for name, a, b in TESTS:
        ra, rb = errors(rows, a, TEST_RHO), errors(rows, b, TEST_RHO)
        ids = sorted(set(ra) & set(rb))
        diffs = {}
        for i in ids:
            diffs.setdefault(ra[i]["iso_week"], []).append(ra[i]["abs_err"] - rb[i]["abs_err"])
        mean, lo, hi = week_bootstrap_ci(diffs, B=BOOT_B, seed=BOOT_SEED)
        _, median, p = wilcoxon_pair([ra[i]["abs_err"] for i in ids], [rb[i]["abs_err"] for i in ids])
        out.append({"test": name, "a": a, "b": b, "rho": TEST_RHO, "n": len(ids), "mean_diff": mean,
                    "ci_lo": lo, "ci_hi": hi, "median_diff": median, "p": p})
    for r, adj in zip(out, holm([r["p"] for r in out])):
        r["p_holm"] = adj
        r["supported"] = bool(adj < ALPHA and r["mean_diff"] > 0)
    return out


def write_csv(path, rows, opener=open):
    with opener(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    started = time.perf_counter()
    with open(os.path.join(cg.DATA_DIR, "grid_cells.json"), encoding="utf-8") as f:
        cells = [tuple(c) for c in json.load(f)["cells"]]
    with httpx.Client(timeout=180) as client:
        fetched, calls = cg.download(client, cells, START, END)
    print(f"download: {fetched} cells fetched now (~{calls:.0f} API calls)", flush=True)

    first, precip, raw_sha = load_period(len(cells))
    offsets, stamps = candidate_offsets(first)
    routes = data.load_routes()
    samples, skipped = draw_samples(routes, precip, offsets, stamps, np.random.default_rng(SEED))
    cases = make_cases(samples, routes)
    print(f"{len(cases)} samples on {len({(s['route_set'], s['route_id']) for s in samples})} routes "
          f"({skipped} candidate departures skipped for missing hours)", flush=True)

    model, _ = final_eval.load_models()
    rows = evaluate(cases, model, log=lambda m: print(m, flush=True))
    mae, tests = mae_table(rows), tests_table(rows)

    os.makedirs(OUT_DIR, exist_ok=True)
    write_csv(os.path.join(OUT_DIR, "per_sample.csv.gz"), rows, opener=gzip.open)
    write_csv(os.path.join(OUT_DIR, "mae.csv"), mae)
    write_csv(os.path.join(OUT_DIR, "tests.csv"), tests)
    summary = {
        "utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_head": (final_eval.git("rev-parse", "HEAD") or "").strip() or None,
        "period": [START.isoformat(), END.isoformat()], "raw_sha256": raw_sha,
        "missing_hours": int(np.isnan(precip).sum()), "skipped_departures": skipped,
        "n_samples": len(cases), "n_holdout_route_samples": sum(s["route_set"] == "holdout" for s in samples),
        "tests": tests,
    }
    with open(os.path.join(OUT_DIR, "summary.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=2, default=float)
        f.write("\n")
    for r in tests:
        print(f"{r['test']} {r['a']} - {r['b']}: n={r['n']} mean diff {r['mean_diff']:.4f} "
              f"[{r['ci_lo']:.4f}, {r['ci_hi']:.4f}], p_holm {r['p_holm']:.3g} -> "
              f"{'supported' if r['supported'] else 'not supported'}", flush=True)
    print(f"done in {time.perf_counter() - started:.0f}s -> {OUT_DIR}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
