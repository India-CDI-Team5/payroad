"""Turn routes x cell histories into Model A samples, split by week, and check gate G1.

A sample is (route, departure time). Each 500 m route point gets the precipitation of its
cell at the moment the car arrives there (hourly values interpolated in time, the same way
the pricing service reads forecasts), so a sample's ground-truth profile needs no API call.

Choices (plan v4 §4.3, §4.4):
- departures fall between 06:00 and 23:59 local time (IST), when rides happen;
- per route, 40% of samples are wet (any point > 0.1 mm) and at least 20% of all samples
  come from the dry season (Dec-Apr) as the no-rain control;
- dates are split into train/val/test = 60/20/20 by ISO week, separately for each season,
  so neighbouring days (which share weather) never straddle two splits;
- held-out routes (routes_holdout.parquet, if present) only get departures from test weeks.

Run from PartB/:  python -m training.build_samples
Writes data/samples.parquet, data/samples_summary.json, figures/H1_*.png, figures/H2_*.png (+ CSV).
"""
import json
import os
from collections import Counter

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
FIG_DIR = os.path.join(os.path.dirname(__file__), "..", "figures")
IST = np.timedelta64(330, "m")                  # India has no daylight saving
WET_MM = 0.1
SAMPLES_PER_ROUTE = 20
HOLDOUT_SAMPLES_PER_ROUTE = 8
WET_SHARE = 0.4
DRY_SEASON_SHARE = 0.2
SPLITS = {"train": 0.6, "val": 0.2, "test": 0.2}
LOCAL_HOURS = (6, 24)                            # [start, end) in local time
SEED = 42

# G1 (milestone 10/3)
G1_MIN_SHARE_U_GE_3 = 0.40
G1_MIN_WET_SHARE = 0.30


def season(month):
    if 6 <= month <= 9:
        return "sw_monsoon"
    if month in (10, 11):
        return "ne_monsoon"
    return "dry"


def load_cells(path):
    """UTC hour stamps (datetime64[m]) and a cells x hours precipitation matrix (mm)."""
    t = pq.read_table(path)
    times = np.array(t.column("time_utc")[0].as_py(), dtype="datetime64[m]")
    precip = np.array([[np.nan if v is None else v for v in row] for row in t.column("precipitation_mm").to_pylist()])
    return times, precip


def arrival_values(precip, cells, t_min, dep_offsets_h):
    """Precipitation at every route point for every departure.

    dep_offsets_h: departure times as fractional hours after the first stamp, shape (D,).
    Returns shape (D, P): value at point p when leaving at departure d.
    """
    pos = dep_offsets_h[:, None] + np.asarray(t_min)[None, :] / 60.0
    lo = np.floor(pos).astype(int)
    hi = np.minimum(lo + 1, precip.shape[1] - 1)
    frac = pos - lo
    rows = np.asarray(cells)[None, :]
    return precip[rows, lo] * (1 - frac) + precip[rows, hi] * frac


def assign_weeks(times, rng):
    """ISO week -> split, chosen at random within each season so every split sees every season."""
    local = times + IST
    weeks = {}
    for t in local.astype("datetime64[D]").astype(object)[::24]:
        iso = t.isocalendar()
        weeks.setdefault((iso[0], iso[1]), Counter())[season(t.month)] += 1
    by_season = {}
    for wk, seasons in weeks.items():
        by_season.setdefault(seasons.most_common(1)[0][0], []).append(wk)
    split_of = {}
    for s, wks in sorted(by_season.items()):
        wks = sorted(wks)
        rng.shuffle(wks)
        n = len(wks)
        n_train, n_val = round(n * SPLITS["train"]), round(n * SPLITS["val"])
        for i, wk in enumerate(wks):
            split_of[wk] = "train" if i < n_train else "val" if i < n_train + n_val else "test"
    return split_of


def candidate_departures(times, split_of, rng, max_trip_min):
    """One random-minute departure per UTC hour, kept when it falls in the local ride window.

    The window is checked on the departure itself: IST is UTC+5:30, so a UTC hour stamp plus
    up to 59 minutes can cross a local hour (and a local day) boundary.
    """
    offsets = np.arange(len(times)) + rng.uniform(0, 1, size=len(times))
    local = times + IST + (offsets % 1 * 60).astype("timedelta64[m]")
    hour = (local.astype("datetime64[h]") - local.astype("datetime64[D]")).astype(int)
    keep = (hour >= LOCAL_HOURS[0]) & (hour < LOCAL_HOURS[1])
    # Leave room for the longest trip before the series ends.
    keep &= offsets + max_trip_min / 60.0 + 1 < len(times)
    days = local[keep].astype("datetime64[D]").astype(object)
    split = np.array([split_of[(d.isocalendar()[0], d.isocalendar()[1])] for d in days])
    seasons = np.array([season(d.month) for d in days])
    return offsets[keep], split, seasons


def stochastic_round(rng, x):
    """floor(x) plus one with probability frac(x): exact on average, so small splits keep the target share."""
    return int(np.floor(x) + (rng.random() < x - np.floor(x)))


def pick(rng, pool, n):
    if len(pool) == 0 or n <= 0:
        return np.array([], dtype=int)
    return rng.choice(pool, size=min(n, len(pool)), replace=False)


def sample_route(route, precip, times, deps, dep_split, dep_season, rng, splits, per_route):
    values = arrival_values(precip, route["cell"], route["t_min"], deps)
    route_max = np.nanmax(values, axis=1)
    wet = route_max > WET_MM
    out = []
    total = sum(SPLITS[s] for s in splits)
    for s in splits:
        n = round(per_route * SPLITS[s] / total)
        n_wet = stochastic_round(rng, n * WET_SHARE)
        n_dry_season = stochastic_round(rng, n * DRY_SEASON_SHARE)
        in_split = dep_split == s
        wet_pick = pick(rng, np.nonzero(in_split & wet)[0], n_wet)
        dry_season_pick = pick(rng, np.nonzero(in_split & ~wet & (dep_season == "dry"))[0], n_dry_season)
        rest = np.setdiff1d(np.nonzero(in_split & ~wet)[0], dry_season_pick)
        other_pick = pick(rng, rest, n - len(wet_pick) - len(dry_season_pick))
        for i in np.concatenate([wet_pick, dry_season_pick, other_pick]).astype(int):
            dep_utc = times[0] + np.timedelta64(int(deps[i] * 60), "m")   # floor: 23:59.6 stays 23:59
            out.append({
                "route_set": route["route_set"], "route_id": route["route_id"], "stratum": route["stratum"],
                "unique_cells": route["unique_cells"], "split": s if route["route_set"] == "main" else "test_holdout",
                "departure_utc": str(dep_utc), "departure_local": str(dep_utc + IST), "season": dep_season[i],
                "wet": bool(wet[i]), "route_mean_mm": float(np.nanmean(values[i])),
                "route_max_mm": float(route_max[i]), "gt_mm": [float(v) for v in values[i]],
            })
    return out


def load_routes(name):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        return []
    rows = pq.read_table(path).to_pylist()
    for r in rows:
        r.setdefault("route_set", "main" if "holdout" not in name else "holdout")
    return rows


def figures(routes, samples):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(FIG_DIR, exist_ok=True)
    strata = ["short", "medium", "long"]
    labels = {"short": "5-15 km", "medium": "15-30 km", "long": "30-60 km"}

    fig, ax = plt.subplots(figsize=(5.5, 3.4))
    top = max(r["unique_cells"] for r in routes)
    bins = np.arange(0.5, top + 1.5)
    ax.hist([[r["unique_cells"] for r in routes if r["stratum"] == s] for s in strata], bins=bins,
            stacked=True, label=[labels[s] for s in strata])
    ax.axvline(2.5, color="0.4", linestyle="--", linewidth=1)
    ax.text(2.6, ax.get_ylim()[1] * 0.92, "U ≥ 3", fontsize=8, color="0.3")
    ax.set_xlabel("Weather grid cells crossed per route (U)")
    ax.set_ylabel("Routes")
    ax.set_xticks(range(1, top + 1))
    ax.legend(title="Route length", frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "H1_unique_cells.png"), dpi=200)
    plt.close(fig)
    with open(os.path.join(FIG_DIR, "H1_unique_cells.csv"), "w", encoding="utf-8") as f:
        f.write("route_set,route_id,stratum,distance_km,unique_cells\n")
        for r in routes:
            f.write(f"{r['route_set']},{r['route_id']},{r['stratum']},{r['distance_km']},{r['unique_cells']}\n")

    wet = [s["route_mean_mm"] for s in samples if s["wet"]]
    fig, ax = plt.subplots(figsize=(5.5, 3.4))
    ax.hist(wet, bins=np.logspace(-3, np.log10(max(wet) + 1e-9), 30))
    ax.set_xscale("log")
    ax.axvline(1.33, color="0.4", linestyle="--", linewidth=1)
    ax.text(1.25, ax.get_ylim()[1] * 0.9, "surcharge threshold\n(β > 1.2)", fontsize=8, color="0.3", ha="right")
    ax.set_xlabel("Route-average precipitation of wet samples (mm/h)")
    ax.set_ylabel("Samples")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "H2_route_rain.png"), dpi=200)
    plt.close(fig)
    with open(os.path.join(FIG_DIR, "H2_route_rain.csv"), "w", encoding="utf-8") as f:
        f.write("split,season,wet,route_mean_mm,route_max_mm\n")
        for s in samples:
            f.write(f"{s['split']},{s['season']},{int(s['wet'])},{s['route_mean_mm']:.4f},{s['route_max_mm']:.4f}\n")


def summarize(routes_main, samples, times):
    main = [s for s in samples if s["route_set"] == "main"]
    share_u3 = sum(r["unique_cells"] >= 3 for r in routes_main) / len(routes_main)
    wet_share = sum(s["wet"] for s in main) / len(main)
    per_split = {}
    for s in main:
        c = per_split.setdefault(s["split"], Counter())
        c["samples"] += 1
        c["wet"] += s["wet"]
        c[s["season"]] += 1
    return {
        "period_utc": [str(times[0]), str(times[-1])],
        "routes": {"main": len(routes_main), "holdout": len({s["route_id"] for s in samples if s["route_set"] == "holdout"})},
        "samples": {"main": len(main), "holdout": len(samples) - len(main)},
        "share_U_ge_3": round(share_u3, 3),
        "wet_sample_share": round(wet_share, 3),
        "dry_season_sample_share": round(sum(s["season"] == "dry" for s in main) / len(main), 3),
        "per_split": {k: dict(v) for k, v in sorted(per_split.items())},
        "G1": {"share_U_ge_3_min": G1_MIN_SHARE_U_GE_3, "wet_share_min": G1_MIN_WET_SHARE,
               "pass": share_u3 >= G1_MIN_SHARE_U_GE_3 and wet_share >= G1_MIN_WET_SHARE},
    }


def main():
    rng = np.random.default_rng(SEED)
    times, precip = load_cells(os.path.join(DATA_DIR, "cells.parquet"))
    routes = load_routes("routes.parquet")
    holdout = load_routes("routes_holdout.parquet")
    max_trip = max(r["t_min"][-1] for r in routes + holdout)

    split_of = assign_weeks(times, rng)
    deps, dep_split, dep_season = candidate_departures(times, split_of, rng, max_trip)

    samples = []
    for r in routes:
        samples += sample_route(r, precip, times, deps, dep_split, dep_season, rng, list(SPLITS), SAMPLES_PER_ROUTE)
    for r in holdout:
        samples += sample_route(r, precip, times, deps, dep_split, dep_season, rng, ["test"], HOLDOUT_SAMPLES_PER_ROUTE)
    for i, s in enumerate(samples):
        s["sample_id"] = i

    pq.write_table(pa.Table.from_pylist(samples), os.path.join(DATA_DIR, "samples.parquet"))
    figures(routes + holdout, samples)
    summary = summarize(routes, samples, times)
    with open(os.path.join(DATA_DIR, "samples_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
