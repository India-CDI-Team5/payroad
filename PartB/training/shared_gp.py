"""Shared spatial GP across concurrent trips, pre-registered in docs/shared-gp.md (committed before this was run).

Within one 10-minute cache window, trips arrive one after another and every cell any earlier trip called is cached
(a call returns the cell's whole hourly series). For each new trip:
  G   (shared GP)  kriging over the 82 cell centres from all cached cells (log1p, Matérn 0.5, plug-in constant mean,
                   hyperparameters fitted on train-split wet hours, fixed below); call cells until the delta-method
                   sd of the route mean (mm/h) < tau, largest |g| sd first; a window's first trip calls its
                   point-centre cell first.
  N   (non-GP)     for each uncached route cell, if every cached cell within r km agrees (max - min < d mm/h at the
                   point times) copy their inverse-distance-squared mean, else call.
  P   (fixed)      point-centre k = budget(U, rho); fill along the route from the chosen + already cached route cells.
  F   (full cache) call every uncached route cell (error 0), reported for calls only.
tau, (r, d) and rho are chosen on the validation split at N = 20 trips per window to stay under 0.97 x 0.5 x F's
calls there. Primary tests on the temporal set (2025-12-01..2026-10-14), window-level paired Wilcoxon, Holm over 2.
Run once.

    python -m training.shared_gp       # from PartB/ (Docker) -> results/shared_gp/
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pyarrow.parquet as pq
import scipy.linalg

from training import final_eval
from training import temporal_check as tc
from training.build_samples import arrival_values
from training.posthoc_placement import select_hp
from weather import data
from weather.methods import gp_fill
from weather.oracle import RouteOracle
from weather.selection import budget
from weather.stats import holm, week_bootstrap_ci, wilcoxon_pair

SPATIAL = {"sigma_f": 0.27657712238875104, "sigma_n": 0.0, "ls_km": 23.324605181388726}   # train fit, docs §2
JIT = 1e-9
WINDOW_MIN = 10
N_PRIMARY = 20
NS = (5, 10, 20, 50)
FRACS = (0.25, 0.5, 0.75)          # call targets as a share of F's calls; 0.5 is the tested one
MARGIN = 0.97
CALL_SLACK = 1.05
WINDOWS = 300
SEED = 20261017
TAUS = [round(0.005 * i, 3) for i in range(1, 101)]
RADII = (9.5, 13.0, 19.0, 27.0)
DRANGE = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0)
PRHOS = [round(0.05 * i, 2) for i in range(1, 21)]
FLAG_MM = 4 / 3
ALPHA = 0.05
BOOT_B, BOOT_SEED = 2000, 42
OUT = os.path.join(final_eval.ROOT, "results", "shared_gp")


# ---------- grid and data ----------
def cell_xy():
    t = pq.read_table(os.path.join(data.DATA_DIR, "cells.parquet"), columns=["cell", "lat", "lon"])
    assert t.column("cell").to_pylist() == list(range(t.num_rows))
    lat, lon = np.array(t.column("lat").to_pylist()), np.array(t.column("lon").to_pylist())
    lat0 = lat.mean()
    return np.column_stack([(lon - lon.mean()) * 111.32 * np.cos(np.radians(lat0)), (lat - lat0) * 110.57])


def main_period():
    t = pq.read_table(os.path.join(data.DATA_DIR, "cells.parquet"), columns=["time_utc", "precipitation_mm"])
    times = np.array(t.column("time_utc")[0].as_py(), dtype="datetime64[m]")
    precip = np.array([[np.nan if v is None else v for v in r] for r in t.column("precipitation_mm").to_pylist()])
    return times, precip


def temporal_period():
    first, precip, sha = tc.load_period(82)
    times = np.datetime64(first.replace(tzinfo=None), "m") + np.arange(precip.shape[1]) * np.timedelta64(60, "m")
    return times, precip, sha


def week_split():
    out = {}
    for s in data.load_samples(["train", "val", "test"]):
        out[data.iso_week(np.datetime64(s["departure_utc"], "m"))] = s["split"]
    return out


def wet_hours(times, precip, keep_week):
    """Hour indices in local 06-23 h of kept weeks, with no missing cell and some cell above 0.1 mm."""
    local = times + data.IST
    hour = (local.astype("datetime64[h]") - local.astype("datetime64[D]")).astype(int)
    days = local.astype("datetime64[D]").astype(object)
    ok = [i for i in range(len(times)) if 6 <= hour[i] < 24 and keep_week(tuple(days[i].isocalendar()[:2]))
          and not np.isnan(precip[:, i]).any() and np.max(precip[:, i]) > data.WET_MM]
    return np.array(ok)


def make_windows(times, precip, hours, routes, n_trips, rng):
    max_h = max(r["t_min"].max() for r in routes) / 60.0
    hours = hours[hours + max_h + 2 < precip.shape[1]]
    out = []
    for h in rng.choice(hours, size=min(WINDOWS, len(hours)), replace=False):
        start = h + rng.uniform(0, 1)
        wk = data.iso_week(times[h])
        trips = []
        for dep, ri in zip(np.sort(start + rng.uniform(0, WINDOW_MIN, n_trips) / 60.0),
                           rng.integers(0, len(routes), n_trips)):
            r = routes[ri]
            y = arrival_values(precip, r["cell"], r["t_min"], np.array([dep]))[0]
            trips.append({"route": r, "dep": dep, "y": y, "main": r["unique_cells"] >= 3 and y.max() > data.WET_MM})
        out.append({"hour": int(h), "week": f"{wk[0]}-W{wk[1]:02d}", "trips": trips})
    return out


# ---------- methods ----------
class Kriger:
    def __init__(self, xy):
        D = np.hypot(*(xy[:, None, :] - xy[None, :, :]).transpose(2, 0, 1))
        self.K = SPATIAL["sigma_f"] ** 2 * np.exp(-D / SPATIAL["ls_km"])
        self.sn2 = SPATIAL["sigma_n"] ** 2

    def post(self, C, Uc):
        c = scipy.linalg.cho_factor(self.K[np.ix_(C, C)] + (self.sn2 + JIT) * np.eye(len(C)), lower=True)
        Kuc = self.K[np.ix_(Uc, C)]
        W = scipy.linalg.cho_solve(c, Kuc.T).T
        return W, self.K[np.ix_(Uc, Uc)] - Kuc @ W.T


def zvals(precip, cells, t_abs):
    lo = np.floor(t_abs).astype(int)
    fr = t_abs - lo
    v = precip[np.asarray(cells)]
    return np.log1p(v[:, lo] * (1 - fr) + v[:, lo + 1] * fr)


def gp_state(kr, precip, C, route, dep, y):
    cell, P = route["cell"], len(route["cell"])
    y_hat = np.empty(P)
    cached = np.isin(cell, C)
    y_hat[cached] = y[cached]
    Uc = sorted(set(cell[~cached].tolist()))
    if not Uc:
        return y_hat, 0.0, Uc, None
    W, S = kr.post(C, Uc)
    pts = np.nonzero(~cached)[0]
    Zc = zvals(precip, C, dep + route["t_min"][pts] / 60.0)
    m = Zc.mean(axis=0)
    ui = {u: i for i, u in enumerate(Uc)}
    rows = np.array([ui[c] for c in cell[pts].tolist()])
    mu = m + np.einsum("pc,cp->p", W[rows], Zc - m)
    y_hat[pts] = np.maximum(np.expm1(mu), 0.0)
    gcell = np.bincount(rows, weights=np.exp(mu) / P, minlength=len(Uc))
    return y_hat, float(np.sqrt(max(gcell @ S @ gcell, 0.0))), Uc, (S, gcell)


def run_trip(method, par, trip, cache, ctx):
    route, dep, y = trip["route"], trip["dep"], trip["y"]
    o = RouteOracle(route["cell"], y)
    if method == "F":
        new = [c for c in o.order if c not in cache]
        cache.update(new)
        return len(new), float(np.mean(y))
    if method == "P":
        chosen = select_hp(o, budget(o.U, par))
        new = [c for c in chosen if c not in cache]
        cache.update(new)
        idx, yy, _ = o.reveal_cells(list(set(chosen) | {c for c in o.order if c in cache}))
        return len(new), float(np.mean(gp_fill(route["s_km"], route["t_min"], idx, yy, ctx["model"]).y_hat))
    calls = 0
    if method == "N":
        r, dmax = par
        xy, y_hat = ctx["xy"], np.empty(len(y))
        first = select_hp(o, 1)[0]
        for c in [first] + [c for c in o.order if c != first]:
            pts = o.points_of(c)
            if c not in cache and cache:
                cand = sorted(cache)
                d = np.hypot(*(xy[cand] - xy[c]).T)
                near = d <= r
                if near.any():
                    v = np.expm1(zvals(ctx["precip"], np.array(cand)[near], dep + route["t_min"][pts] / 60.0))
                    if np.max(v.max(axis=0) - v.min(axis=0)) < dmax:
                        w = 1.0 / d[near] ** 2
                        y_hat[pts] = w @ v / w.sum()
                        continue
            if c not in cache:
                cache.add(c)
                calls += 1
            y_hat[pts] = y[pts]
        return calls, float(np.mean(y_hat))
    if method == "G":
        if not cache:
            cache.add(select_hp(o, 1)[0])
            calls += 1
        while True:
            y_hat, sd, Uc, extra = gp_state(ctx["kr"], ctx["precip"], sorted(cache), route, dep, y)
            if not Uc or sd < par:
                return calls, float(np.mean(y_hat))
            S, g = extra
            cache.add(Uc[int(np.argmax(np.abs(g) * np.sqrt(np.maximum(np.diag(S), 0))))])
            calls += 1
    raise ValueError(method)


def run_windows(method, par, windows, ctx):
    """Per window: (calls, trips, summed |error| over MAIN-like trips, their count, flag agreements)."""
    out = []
    for w in windows:
        cache, calls, err, n, agree = set(), 0, 0.0, 0, 0
        for tr in w["trips"]:
            c, m_hat = run_trip(method, par, tr, cache, ctx)
            calls += c
            if tr["main"]:
                m = float(np.mean(tr["y"]))
                err += abs(m_hat - m)
                n += 1
                agree += (m_hat > FLAG_MM) == (m > FLAG_MM)
        out.append((calls, len(w["trips"]), err, n, agree))
    return np.array(out, dtype=np.float64)


def calls_mae(stats):
    return float(stats[:, 0].sum() / stats[:, 1].sum()), float(stats[:, 2].sum() / stats[:, 3].sum())


# ---------- tuning (validation only) ----------
def tune(val_windows, ctx, frac):
    full = calls_mae(run_windows("F", None, val_windows, ctx))[0]
    target = MARGIN * frac * full
    cache = ctx.setdefault("val_cache", {})                 # keyed by the window set: one per N

    def cm(meth, par):
        key = (id(val_windows), meth, par)
        if key not in cache:
            cache[key] = calls_mae(run_windows(meth, par, val_windows, ctx))
        return cache[key]

    g = [(t, *cm("G", t)) for t in TAUS]
    under = [x for x in g if x[1] <= target]
    tau = max(under, key=lambda x: (x[1], -x[0]))[0] if under else min(g, key=lambda x: (x[1], x[0]))[0]
    best = {}
    for meth, grid in (("N", [(r, d) for r in RADII for d in DRANGE]), ("P", PRHOS)):
        cand = [(p, *cm(meth, p)) for p in grid]
        ok = [x for x in cand if x[1] <= target]
        best[meth] = (min(ok, key=lambda x: (x[2], str(x[0]))) if ok else min(cand, key=lambda x: (x[1], x[2])),
                      not ok)
    return {"frac": frac, "full_calls": full, "target": target, "G": tau, "G_val": cm("G", tau),
            "N": best["N"][0][0], "N_val": best["N"][0][1:], "P": best["P"][0][0], "P_val": best["P"][0][1:],
            "over_target": (not under) or best["N"][1] or best["P"][1]}


# ---------- tests ----------
def window_test(sg, so, windows):
    keep = (sg[:, 3] > 0) & (so[:, 3] > 0)
    eg, eo = sg[keep, 2] / sg[keep, 3], so[keep, 2] / so[keep, 3]
    by = defaultdict(list)
    for w, d in zip([w for w, k in zip(windows, keep) if k], eg - eo):
        by[w["week"]].append(d)
    mean, lo, hi = week_bootstrap_ci(by, B=BOOT_B, seed=BOOT_SEED)
    _, med, p = wilcoxon_pair(eg, eo)
    return {"windows": int(keep.sum()), "mean_diff": mean, "ci_lo": lo, "ci_hi": hi, "median_diff": med, "p": p}


def main(smoke=False):
    """smoke: 3 windows, N = 20, and every evaluation set replaced by validation hours (checks code, sees no test data)."""
    global WINDOWS, NS, TAUS
    if smoke:
        WINDOWS, NS, TAUS = 3, (N_PRIMARY,), TAUS[::10]
    log = lambda m: print(m, flush=True)  # noqa: E731
    xy = cell_xy()
    model, _ = final_eval.load_models()
    routes = [r for k, r in sorted(data.load_routes().items()) if k[0] == "main"]
    split_of = week_split()
    m_times, m_precip = main_period()
    t_times, t_precip, sha = temporal_period()
    ctxs = {"main": {"xy": xy, "model": model, "kr": Kriger(xy), "precip": m_precip},
            "temporal": {"xy": xy, "model": model, "kr": Kriger(xy), "precip": t_precip}}
    hours = {"val": wet_hours(m_times, m_precip, lambda wk: split_of.get(wk) == "val"),
             "MAIN-test": wet_hours(m_times, m_precip, lambda wk: split_of.get(wk) == "test"),
             "temporal": wet_hours(t_times, t_precip, lambda wk: True)}
    src = {"val": ("main", m_times), "MAIN-test": ("main", m_times), "temporal": ("temporal", t_times)}
    if smoke:
        hours = {s: hours["val"] for s in hours}
        src = {s: ("main", m_times) for s in src}

    summary = {"git_head": (final_eval.git("rev-parse", "HEAD") or "").strip() or None, "temporal_sha256": sha,
               "spatial": SPATIAL, "wet_hours": {k: len(v) for k, v in hours.items()}, "runs": {}, "tests": []}
    for N in NS:
        rng = np.random.default_rng([SEED, N])
        wins = {s: make_windows(src[s][1], ctxs[src[s][0]]["precip"], hours[s], routes, N, rng) for s in hours}
        for frac in FRACS:
            if N != N_PRIMARY and frac != 0.5:
                continue
            ch = tune(wins["val"], ctxs["main"], frac)
            log(f"N={N} frac={frac} tuned: {json.dumps(ch, default=float)}")
            run = {"choice": ch}
            for s in ("MAIN-test", "temporal"):
                ctx = ctxs[src[s][0]]
                st = {m: run_windows(m, p, wins[s], ctx) for m, p in (("F", None), ("G", ch["G"]), ("N", ch["N"]),
                                                                     ("P", ch["P"]))}
                run[s] = {m: {"calls": calls_mae(v)[0], "mae": calls_mae(v)[1],
                              "flag_agree": float(v[:, 4].sum() / v[:, 3].sum())} for m, v in st.items()}
                if N == N_PRIMARY and frac == 0.5:
                    for h, other in (("S1", "N"), ("S2", "P")):
                        t = {"test": f"{h}-{'b' if s == 'temporal' else 'a'}", "set": s, "vs": other,
                             "G_calls": run[s]["G"]["calls"], f"{other}_calls": run[s][other]["calls"],
                             "G_mae": run[s]["G"]["mae"], f"{other}_mae": run[s][other]["mae"],
                             **window_test(st["G"], st[other], wins[s])}
                        t["calls_ok"] = t["G_calls"] <= CALL_SLACK * t[f"{other}_calls"]
                        summary["tests"].append(t)
                log(f"  {s}: " + "  ".join(f"{m} calls {v['calls']:.3f} MAE {v['mae']:.4f}" for m, v in run[s].items()))
            summary["runs"][f"N{N}_f{frac}"] = run

    primary = [t for t in summary["tests"] if t["set"] == "temporal"]
    for t, adj in zip(primary, holm([t["p"] for t in primary])):
        t["p_holm"] = adj
    for t in summary["tests"]:
        t["role"] = "primary" if t["set"] == "temporal" else "supporting"
        t.setdefault("p_holm", None)
        sig = t["p_holm"] is not None and t["p_holm"] < ALPHA
        t["passed"] = bool(t["mean_diff"] < 0 and t["calls_ok"] and (sig or t["role"] == "supporting"))
    summary["all_passed"] = all(t["passed"] for t in summary["tests"])
    out = os.path.join(OUT, "smoke") if smoke else OUT
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=2, default=float)
        f.write("\n")
    for t in summary["tests"]:
        log(f'{t["test"]} G vs {t["vs"]} on {t["set"]}: MAE {t["G_mae"]:.4f} vs {t[t["vs"] + "_mae"]:.4f}, calls '
            f'{t["G_calls"]:.3f} vs {t[t["vs"] + "_calls"]:.3f}, p {t["p"]:.3g}, p_holm {t["p_holm"]}, '
            f'{t["role"]} -> {"pass" if t["passed"] else "FAIL"}')
    log(f"ALL PASSED: {summary['all_passed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(smoke="--smoke" in sys.argv[1:]))
