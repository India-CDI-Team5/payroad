"""Cluster check of the key paired tests (2026-10-16, external review; post hoc robustness, not a new result).

The same route appears in several test weeks, so per-sample Wilcoxon tests treat repeated routes as independent.
This averages the paired error difference within each route (and, separately, within each ISO week) and runs the
same two-sided Wilcoxon signed-rank test on those cluster means. Reads only existing per-sample results.

    python -m training.cluster_check     # from PartB/ -> results/cluster_check/summary.json
"""
import csv
import gzip
import json
import os
from collections import defaultdict

import numpy as np
from scipy.stats import wilcoxon

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
MAIN = os.path.join(ROOT, "results", "model_a", "test_per_sample.csv.gz")
POSTHOC = os.path.join(ROOT, "results", "posthoc", "model_a", "placement_per_sample.csv.gz")
TEMPORAL = os.path.join(ROOT, "results", "temporal", "per_sample.csv.gz")
OUT = os.path.join(ROOT, "results", "cluster_check")
RHO = "0.5"


def rows(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def errors(rs, method, subset_ok):
    return {r["sample_id"]: float(r["abs_err"]) for r in rs if r["method"] == method and r["rho"] and float(r["rho"]) == 0.5
            and subset_ok(r)}


def cluster_test(a, b, key):
    """a, b: sample_id -> abs_err; key: sample_id -> cluster label. Wilcoxon on cluster means of a - b."""
    by = defaultdict(list)
    for sid in set(a) & set(b):
        by[key[sid]].append(a[sid] - b[sid])
    means = np.array([np.mean(v) for v in by.values()])
    p = float(wilcoxon(means, alternative="two-sided").pvalue)
    return {"n_samples": int(sum(len(v) for v in by.values())), "n_clusters": len(means),
            "mean_diff": float(means.mean()), "p": p}


def main():
    m = rows(MAIN)
    main_ok = lambda r: "MAIN" in r["subset_flags"]  # noqa: E731
    route = {r["sample_id"]: (r["route_set"], r["route_id"]) for r in m}
    week = {r["sample_id"]: r["iso_week"] for r in m}
    m1, m2 = errors(m, "M1", main_ok), errors(m, "M2", main_ok)
    ph = rows(POSTHOC)
    ph_ok = lambda r: r["subset"] == "MAIN"  # noqa: E731
    hp, m2p = errors(ph, "H-P", ph_ok), errors(ph, "M2", ph_ok)
    t = rows(TEMPORAL)
    t_route = {r["sample_id"]: (r["route_set"], r["route_id"]) for r in t}
    t_week = {r["sample_id"]: r["iso_week"] for r in t}
    tb1, tm2, thp = (errors(t, x, lambda r: True) for x in ("B1", "M2", "H-P"))

    out = {
        "main_test_routes": len({route[s] for s in m2}), "main_test_weeks": len({week[s] for s in m2}),
        "pre_M2_vs_M1": {"route": cluster_test(m2, m1, route), "week": cluster_test(m2, m1, week)},
        "posthoc_HP_vs_M2": {"route": cluster_test(hp, m2p, route), "week": cluster_test(hp, m2p, week)},
        "temporal_HP_vs_M2": {"route": cluster_test(thp, tm2, t_route), "week": cluster_test(thp, tm2, t_week)},
        "temporal_M2_vs_B1": {"route": cluster_test(tm2, tb1, t_route), "week": cluster_test(tm2, tb1, t_week)},
    }
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
