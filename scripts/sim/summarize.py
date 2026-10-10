"""Summary CSVs of the mechanism experiments E1~E6 (ml-design v5 §6.4, §6.6, card C4).

Run from the repository root after the six runner scenarios (card C4 step 1):
  python scripts/sim/summarize.py

Every statistic is computed per run first (one config × seed × sweep cell × variant, 300 deals), then
averaged over seeds with a percentile bootstrap 95% CI over seeds (B = 2000, seed 42). A run whose
statistic is undefined (for example no MATCHED deal for a markup) is left out of that statistic.

Definitions fixed here:
  markup          final_price / base_price of MATCHED deals (markup_dry: final_price / base_dry, E6)
  match_rate      MATCHED deals / all deals
  duration        duration_sec of all deals (time to MATCHED or to the end by TTL / round limit);
                  time_to_match (E3) uses MATCHED deals only
  E1_trend        spearman_n_markup: Spearman ρ between n and the run markup median, computed within each
                  seed over n = 1..10 and averaged over seeds. diff_n1_minus_n10: run markup median at
                  n = 1 minus at n = 10, paired by seed. monotone_decrease = ρ < 0 and ci_lo > 0
  E2_rounds       share of all deals with each round_count; E2_end: shares of MATCHED / TTL / ROUND_LIMIT
  E5_tau          rank shares among MATCHED deals the rider closed by picking a bid (chosen_rank ≥ 1);
                  deals closed by the driver taking the offer have chosen_rank 0 and no rank
"""
import argparse
import csv
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
RAW = os.path.join(ROOT, "results", "sim", "raw")
OUT = os.path.join(ROOT, "results", "sim")
B = 2000
BOOT_SEED = 42

TEXT = ("run_id", "config", "status", "end_reason", "match_path", "mode", "beta_mode")
NUMBER = ("seed", "n_drivers", "markup", "markup_dry", "chosen_rank", "winner_pickup_eta", "round_count",
          "duration_sec", "param_offer_ttl", "param_round_limit", "param_tau")


def load(path):
    """deals_out.csv as column arrays: text columns as str arrays, numbers as float (blank = nan)."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {c: header.index(c) for c in TEXT + NUMBER}
        cols = {c: [] for c in idx}
        for row in reader:
            for c, i in idx.items():
                cols[c].append(row[i])
    out = {c: np.array(cols[c]) for c in TEXT}
    for c in NUMBER:
        out[c] = np.array([float(v) if v != "" else np.nan for v in cols[c]])
    out["matched"] = out["status"] == "MATCHED"
    return out


def runs(d):
    """Row indices of every run, one run = run_id × mode × beta_mode (E3 and E6 play two variants per run)."""
    key = np.char.add(np.char.add(np.char.add(d["run_id"], "|"), np.char.add(d["mode"], "|")), d["beta_mode"])
    _, first, inverse = np.unique(key, return_index=True, return_inverse=True)
    order = np.argsort(inverse, kind="stable")
    bounds = np.cumsum(np.bincount(inverse))[:-1]
    groups = np.split(order, bounds)
    return [groups[i] for i in np.argsort(first)]       # in file order


def bootstrap(values, b=B, seed=BOOT_SEED):
    """(mean, ci_lo, ci_hi) over the per-seed values, percentile bootstrap. nan values are dropped."""
    v = np.asarray(values, dtype=np.float64)
    v = v[~np.isnan(v)]
    if len(v) == 0:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    means = v[rng.integers(0, len(v), size=(b, len(v)))].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(v.mean()), float(lo), float(hi)


def mean(values):
    v = np.asarray(values, dtype=np.float64)
    v = v[~np.isnan(v)]
    return float(v.mean()) if len(v) else np.nan


def rankdata(a):
    """Ranks starting at 1, ties get their average rank."""
    a = np.asarray(a, dtype=np.float64)
    order = np.argsort(a, kind="stable")
    ranks = np.empty(len(a))
    ranks[order] = np.arange(1, len(a) + 1)
    _, inv = np.unique(a, return_inverse=True)
    sums = np.bincount(inv, weights=ranks)
    return (sums / np.bincount(inv))[inv]


def spearman(x, y):
    x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    keep = ~(np.isnan(x) | np.isnan(y))
    if keep.sum() < 3:
        return np.nan
    rx, ry = rankdata(x[keep]), rankdata(y[keep])
    if rx.std() == 0 or ry.std() == 0:
        return np.nan
    return float(np.corrcoef(rx, ry)[0, 1])


def median_or_nan(v):
    v = v[~np.isnan(v)]
    return float(np.median(v)) if len(v) else np.nan


def run_stats(d, g):
    """Per-run statistics of one run's rows g."""
    m = d["matched"][g]
    picked = m & (d["chosen_rank"][g] >= 1)
    rank = d["chosen_rank"][g][picked]
    return {
        "config": d["config"][g[0]], "seed": d["seed"][g[0]], "n": d["n_drivers"][g[0]],
        "mode": d["mode"][g[0]], "beta_mode": d["beta_mode"][g[0]],
        "offer_ttl": d["param_offer_ttl"][g[0]], "round_limit": d["param_round_limit"][g[0]],
        "tau": d["param_tau"][g[0]],
        "deals": len(g),
        "match_rate": float(m.mean()),
        "markup_median": median_or_nan(d["markup"][g][m]),
        "markup_dry_median": median_or_nan(d["markup_dry"][g][m]),
        "duration_median": float(np.median(d["duration_sec"][g])),
        "duration_q": np.percentile(d["duration_sec"][g], [25, 50, 75, 90]),
        "time_to_match_median": median_or_nan(d["duration_sec"][g][m]),
        "winner_eta_mean": mean(d["winner_pickup_eta"][g][m]),
        "ttl_share": float((d["end_reason"][g] == "TTL").mean()),
        "round_limit_share": float((d["end_reason"][g] == "ROUND_LIMIT").mean()),
        "round_count": d["round_count"][g],
        "rank1": float((rank == 1).mean()) if len(rank) else np.nan,
        "rank2": float((rank == 2).mean()) if len(rank) else np.nan,
        "rank3plus": float((rank >= 3).mean()) if len(rank) else np.nan,
    }


def per_run(path):
    d = load(path)
    return [run_stats(d, g) for g in runs(d)]


def by(rows, *keys):
    """Ordered groups of run rows by the given keys."""
    out = {}
    for r in rows:
        out.setdefault(tuple(r[k] for k in keys), []).append(r)
    return out


def e1(rows):
    summary, trend = [], []
    for (config,), rs in by(rows, "config").items():
        for (n,), cell in sorted(by(rs, "n").items()):
            mk, mr = bootstrap([r["markup_median"] for r in cell]), bootstrap([r["match_rate"] for r in cell])
            summary.append([config, int(n), len(cell), *mk, *mr])
        seeds = by(rs, "seed")
        rhos, diffs = [], []
        for _, sr in sorted(seeds.items()):
            med = {r["n"]: r["markup_median"] for r in sr}
            ns = sorted(med)
            rhos.append(spearman(ns, [med[k] for k in ns]))
            diffs.append(med.get(1.0, np.nan) - med.get(10.0, np.nan))
        rho = mean(rhos)
        diff, lo, hi = bootstrap(diffs)
        trend.append([config, rho, diff, lo, hi, int(bool(rho < 0 and lo > 0))])
    return summary, trend


def e2(rows):
    rounds, duration, end = [], [], []
    for (config,), rs in by(rows, "config").items():
        top = int(max(r["round_count"].max() for r in rs))
        for k in range(top + 1):
            rounds.append([config, k, mean([(r["round_count"] == k).mean() for r in rs])])
        q = np.array([r["duration_q"] for r in rs]).mean(axis=0)
        duration.append([config, *q])
        end.append([config, mean([r["match_rate"] for r in rs]), mean([r["ttl_share"] for r in rs]),
                    mean([r["round_limit_share"] for r in rs])])
    return rounds, duration, end


def e3(rows):
    return [[config, mode, *bootstrap([r["match_rate"] for r in rs]), mean([r["time_to_match_median"] for r in rs]),
             mean([r["winner_eta_mean"] for r in rs])] for (config, mode), rs in by(rows, "config", "mode").items()]


def e4(rows):
    out = []
    for (config, ttl, rl), rs in by(rows, "config", "offer_ttl", "round_limit").items():
        out.append([config, int(ttl), int(rl), mean([r["match_rate"] for r in rs]),
                    mean([r["duration_median"] for r in rs])])
    return out


def e5(rows):
    return [[config, tau, mean([r["rank1"] for r in rs]), mean([r["rank2"] for r in rs]),
             mean([r["rank3plus"] for r in rs]), mean([r["markup_median"] for r in rs]),
             mean([r["winner_eta_mean"] for r in rs])] for (config, tau), rs in by(rows, "config", "tau").items()]


def e6(rows):
    return [[config, beta_mode, mean([r["duration_median"] for r in rs]), mean([r["match_rate"] for r in rs]),
             mean([r["markup_dry_median"] for r in rs])] for (config, beta_mode), rs in
            by(rows, "config", "beta_mode").items()]


OUTPUTS = {
    "e1": [("E1_summary.csv", ["config", "n", "runs", "markup_median", "ci_lo", "ci_hi", "match_rate", "mr_ci_lo",
                               "mr_ci_hi"]),
           ("E1_trend.csv", ["config", "spearman_n_markup", "diff_n1_minus_n10", "ci_lo", "ci_hi",
                             "monotone_decrease"])],
    "e2": [("E2_rounds.csv", ["config", "round_count", "share"]),
           ("E2_duration.csv", ["config", "p25", "p50", "p75", "p90"]),
           ("E2_end.csv", ["config", "matched", "ttl", "round_limit"])],
    "e3": [("E3_fixed.csv", ["config", "mode", "match_rate", "ci_lo", "ci_hi", "time_to_match_median",
                             "winner_eta_mean"])],
    "e4": [("E4_heatmap.csv", ["config", "offer_ttl", "round_limit", "match_rate", "duration_median"])],
    "e5": [("E5_tau.csv", ["config", "tau", "rank1_share", "rank2_share", "rank3plus_share", "markup_median",
                           "winner_eta_mean"])],
    "e6": [("E6_weather.csv", ["config", "beta_mode", "duration_median", "match_rate", "markup_dry_median"])],
}
SUMMARIZERS = {"e1": e1, "e2": e2, "e3": lambda r: (e3(r),), "e4": lambda r: (e4(r),), "e5": lambda r: (e5(r),),
               "e6": lambda r: (e6(r),)}


def cell(v):
    if isinstance(v, (float, np.floating)):
        return "" if np.isnan(v) else f"{float(v):.6f}"
    return v


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows([[cell(v) for v in r] for r in rows])


def summarize(scenario, raw_dir=RAW, out_dir=OUT):
    """Writes the scenario's summary CSVs; returns {file name: row count}."""
    tables = SUMMARIZERS[scenario](per_run(os.path.join(raw_dir, scenario, "deals_out.csv")))
    os.makedirs(out_dir, exist_ok=True)
    counts = {}
    for (name, header), rows in zip(OUTPUTS[scenario], tables):
        write(os.path.join(out_dir, name), header, rows)
        counts[name] = len(rows)
    return counts


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--raw-dir", default=RAW)
    p.add_argument("--out-dir", default=OUT)
    p.add_argument("scenarios", nargs="*", default=list(OUTPUTS))
    a = p.parse_args()
    for s in a.scenarios:
        path = os.path.join(a.raw_dir, s, "deals_out.csv")
        if not os.path.exists(path):
            print(f"{s}: skipped, no {path}")
            continue
        print(f"{s}: " + ", ".join(f"{k} {v} rows" for k, v in summarize(s, a.raw_dir, a.out_dir).items()))


if __name__ == "__main__":
    main()
