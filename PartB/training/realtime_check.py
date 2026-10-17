"""Prospective real-time forecast check, pre-registered in docs/realtime-check.md (committed before collection began).

Each snapshot from training.realtime_collect is what the service would have received at its fetch time T. A
departure at T (lead 0, the service's condition) on a U >= 3 route reads each point's forecast at its arrival time
from that snapshot; the truth is the snapshot's full query. Snapshots fetched 2026-10-18T00:00Z..2026-11-17T23:59Z
with T in IST 06:00-23:59 are used; up to 4 wet routes per snapshot are drawn. The frozen methods B1, M1, M2 and
H-P (Mid) run as in training.temporal_check. Tests R-1 M2 - H-P and R-2 B1 - M2 at k/U = 0.5, two-sided Wilcoxon,
Holm over the two, supported if p_holm < 0.05 and the mean difference is positive; 95% intervals by day blocks.
With fewer than 200 wet samples the result is descriptive only. Run once, on or after 2026-11-18.

Run from PartB/ (Docker, parquet):
    python -m training.realtime_check            # -> results/realtime_check/
    python -m training.realtime_check --smoke    # snapshots before the window only, prints counts only
"""
import argparse
import datetime
import glob
import gzip
import hashlib
import json
import os
import sys

import numpy as np

from training import final_eval
from training import temporal_check as tc
from training.build_samples import arrival_values
from weather import data
from weather.oracle import RouteOracle

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "realtime")
START = datetime.datetime(2026, 10, 18, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2026, 11, 18, tzinfo=datetime.timezone.utc)          # exclusive
IST = datetime.timedelta(hours=5, minutes=30)
PER_SNAPSHOT = 4
SEED = 20261118
MIN_SAMPLES = 200
SAMPLE_ID_BASE = 970000
OUT_DIR = os.path.join(final_eval.ROOT, "results", "realtime_check")


def load_snapshot(path):
    with open(path, "rb") as f:
        raw = f.read()
    d = json.loads(raw)
    t = datetime.datetime.strptime(d["fetched_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    t0 = datetime.datetime.fromisoformat(d["hourly"][0]["time"][0]).replace(tzinfo=datetime.timezone.utc)
    precip = np.array([[np.nan if v is None else float(v) for v in h["precipitation"]] for h in d["hourly"]])
    return t, t0, precip, raw


def snapshots(smoke):
    out = []
    for path in sorted(glob.glob(os.path.join(RAW, "*.json"))):
        t, t0, precip, raw = load_snapshot(path)
        in_window = START <= t < END
        if (smoke and t < START) or (not smoke and in_window):
            if 6 <= (t + IST).hour <= 23:
                out.append((path, t, t0, precip, raw))
    return out


def draw(routes, snaps, rng):
    samples = []
    keys = [k for k in sorted(routes) if routes[k]["unique_cells"] >= 3]
    for path, t, t0, precip, _ in snaps:
        offset = (t - t0) / datetime.timedelta(hours=1)
        wet = []
        for k in keys:
            r = routes[k]
            if offset + r["t_min"].max() / 60.0 + 1 > precip.shape[1] - 1:
                continue
            y = arrival_values(precip, r["cell"], r["t_min"], np.array([offset]))[0]
            if not np.isnan(y).any() and y.max() > data.WET_MM:
                wet.append((k, y))
        for i in np.sort(rng.choice(len(wet), size=min(PER_SNAPSHOT, len(wet)), replace=False)) if wet else []:
            k, y = wet[i]
            samples.append({"route_set": k[0], "route_id": k[1], "snapshot": os.path.basename(path),
                            "day": (t + IST).strftime("%Y-%m-%d"), "gt_mm": y})
    return samples


def make_cases(samples, routes):
    return [{"sample": {**s, "sample_id": SAMPLE_ID_BASE + i}, "route": routes[(s["route_set"], s["route_id"])],
             "y": s["gt_mm"], "oracle": RouteOracle(routes[(s["route_set"], s["route_id"])]["cell"], s["gt_mm"]),
             "s": routes[(s["route_set"], s["route_id"])]["s_km"], "t": routes[(s["route_set"], s["route_id"])]["t_min"],
             "week": s["day"]} for i, s in enumerate(samples)]          # "week" = the bootstrap block, here a day


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--smoke", action="store_true", help="snapshots before the window only; prints counts only")
    a = p.parse_args(argv)
    snaps = snapshots(a.smoke)
    digest = hashlib.sha256()
    for s in snaps:
        digest.update(s[4])
    routes = data.load_routes()
    samples = draw(routes, snaps, np.random.default_rng(SEED))
    cases = make_cases(samples, routes)
    print(f"{len(snaps)} snapshots, {len(cases)} wet samples on {len({s['day'] for s in samples})} days", flush=True)
    if not cases:
        return 0
    model, _ = final_eval.load_models()
    rows = tc.evaluate(cases, model, log=lambda m: print(m, flush=True))
    if a.smoke:
        print(f"smoke ok: {len(rows)} method rows (values not shown)")
        return 0
    mae = tc.mae_table(rows)
    tests = tc.tests_table(rows) if len(cases) >= MIN_SAMPLES else []
    for t, name in zip(tests, ("R-1", "R-2")):
        t["test"] = name
    os.makedirs(OUT_DIR, exist_ok=True)
    tc.write_csv(os.path.join(OUT_DIR, "per_sample.csv.gz"), rows, opener=gzip.open)
    tc.write_csv(os.path.join(OUT_DIR, "mae.csv"), mae)
    if tests:
        tc.write_csv(os.path.join(OUT_DIR, "tests.csv"), tests)
    summary = {"utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "git_head": (final_eval.git("rev-parse", "HEAD") or "").strip() or None,
               "window": [START.isoformat(), END.isoformat()], "snapshots": len(snaps),
               "snapshots_sha256": digest.hexdigest(), "n_samples": len(cases),
               "days": len({s["day"] for s in samples}), "descriptive_only": not tests, "tests": tests}
    with open(os.path.join(OUT_DIR, "summary.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=2, default=float)
        f.write("\n")
    for r in tests:
        print(f"{r['test']} {r['a']} - {r['b']}: n={r['n']} mean diff {r['mean_diff']:.4f} "
              f"[{r['ci_lo']:.4f}, {r['ci_hi']:.4f}], p_holm {r['p_holm']:.3g} -> "
              f"{'supported' if r['supported'] else 'not supported'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
