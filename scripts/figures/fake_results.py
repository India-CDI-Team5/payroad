"""Plausible fake values for every input CSV of make_all, with the real column names (tests only).

    python scripts/figures/fake_results.py <empty tmp dir>

Refuses to write inside the repository's results/: fake figures must never be committed.
"""
import csv
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REAL_RESULTS = os.path.normpath(os.path.join(HERE, "..", "..", "results"))
METHODS = ["B0", "B1", "B1-L", "B2", "B2-L", "M1", "M2"]
CONFIGS = ["C1", "C2", "C3", "C4"]
RHOS = [0.25, 0.5, 0.75, 1.0]
# MAE at rho = 1 and how much a smaller budget adds (B0 does not depend on the budget).
MAE = {"B0": (0.27, 0.0), "B1": (0.06, 0.12), "B1-L": (0.05, 0.11), "B2": (0.05, 0.13), "B2-L": (0.04, 0.10),
       "M1": (0.04, 0.09), "M2": (0.03, 0.07)}


def _write(root, rel, header, rows):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        for r in rows:
            w.writerow([f"{v:.6f}" if isinstance(v, float) else v for v in r])
    return path


def _mae(m, frac):
    base, extra = MAE[m]
    return base + extra * (1 - frac) ** 2


def model_a(root, rng):
    curve, kabs, t1 = [], [], []
    for subset, n in (("MAIN", 491), ("ALL", 1188), ("HOLDOUT", 210)):
        for m in METHODS:
            for rho in RHOS:
                v = _mae(m, rho)
                curve.append([subset, m, rho, n, v, v * 0.8, v * 1.2])
            for k in range(1, 9):
                v = _mae(m, min(1.0, k / 4))
                kabs.append([subset, m, k, n - 20 * k, v, v * 0.8, v * 1.2])
            saving = "" if m == "B0" else {"B1": 0.0}.get(m, round(rng.uniform(0.1, 0.4), 6))
            t1.append([subset, m, n, _mae(m, 0.25), _mae(m, 0.5), _mae(m, 0.75), _mae(m, 0.5) * 0.8,
                       _mae(m, 0.5) * 1.2, rng.uniform(0.3, 0.7), rng.uniform(0.9, 0.99), saving])
    _write(root, "model_a/F1_curve.csv", ["subset", "method", "rho", "n", "mae", "ci_lo", "ci_hi"], curve)
    _write(root, "model_a/F1_kabs.csv", ["subset", "method", "k", "n", "mae", "ci_lo", "ci_hi"], kabs)
    _write(root, "model_a/T1_table.csv", ["subset", "method", "n", "mae_rho25", "mae_rho50", "mae_rho75", "ci50_lo",
                                          "ci50_hi", "max_hit_rho50", "agree_rho50", "saving_vs_B1"], t1)
    _write(root, "model_a/F2_coverage.csv", ["method", "rho", "n", "cov_points", "cov_mean"],
           [[m, rho, 491, 0.97 - 0.02 * rho, 0.9 - 0.05 * rho] if rho < 1 else [m, rho, 0, "", ""]
            for m in ("M1", "M2") for rho in RHOS])
    bins = []
    for m in ("M1", "M2"):
        for rho in RHOS[:3]:
            for b in range(1, 6):
                bins.append([m, rho, b, 0.05 * b, 0.05 * (b + 1), 98, 0.03 + 0.02 * b])
    _write(root, "model_a/F2_uncertainty_bins.csv", ["method", "rho", "bin", "s_lo", "s_hi", "n", "mean_abs_err"], bins)
    _write(root, "model_a/F2_spearman.csv", ["method", "rho", "n", "spearman"],
           [[m, rho, 491, 0.5 + 0.02 * i] if rho < 1 else [m, rho, 0, ""]
            for i, m in enumerate(("M1", "M2")) for rho in RHOS])
    t2 = []
    for coef in (0.1, 0.15, 0.2, 0.3):
        for rank, m in enumerate(METHODS[::-1], start=1):
            t2.append([coef, m, 1188, 0.99 - 0.01 * rank, 0.005 * rank, 0.004 * rank, rank])
    _write(root, "model_a/T2_beta_sensitivity.csv", ["coef", "method", "n", "agree", "over_rate", "under_rate",
                                                     "rank"], t2)
    tests = []
    for a, b in (("B2", "B1"), ("M1", "B2-L"), ("M1", "B1"), ("M2", "M1")):
        for rho in RHOS[:3]:
            p = rng.uniform(0, 0.2)
            tests.append([a, b, rho, 491, rng.uniform(-0.03, 0.02), -0.04, 0.03, 0.0, p, min(1.0, p * 4),
                          int(p * 4 < 0.05)])
    _write(root, "model_a/stats_tests.csv", ["a", "b", "rho", "n", "mean_diff", "ci_lo", "ci_hi", "median_diff", "p",
                                             "p_holm", "significant"], tests)


def tables(root):
    _write(root, "tables/T3_calls.csv", ["method", "routes", "mean_calls", "median_calls", "total_calls",
                                         "saving_vs_current"],
           [["current_points", 100, 6.69, 6.0, 669, 0.0], ["current_cells", 100, 3.72, 3.0, 372, 0.4439],
            ["all_cells_U", 100, 4.13, 4.0, 413, 0.3827], ["proposed_M2", 100, 2.38, 2.0, 238, 0.6442]])
    _write(root, "tables/T3_cache.csv", ["key_scheme", "trips", "ttl_min", "lookups", "unique_keys", "hits", "hit_rate",
                                         "api_calls"],
           [["current_points_2dp", 500, 10, 2630, 60, 2570, 0.9772, 60],
            ["current_points_cell", 500, 10, 2630, 7, 2623, 0.9973, 7],
            ["proposed_M2_cell", 500, 10, 758, 5, 753, 0.9934, 5]])


def sim(root, rng):
    e1 = []
    for i, c in enumerate(CONFIGS):
        for n in range(1, 11):
            m = 1.6 - 0.05 * n + 0.04 * i
            e1.append([c, n, 30, m, m - 0.04, m + 0.04, 0.5 + 0.04 * n, 0.45 + 0.04 * n, 0.55 + 0.04 * n])
    _write(root, "sim/E1_summary.csv", ["config", "n", "runs", "markup_median", "ci_lo", "ci_hi", "match_rate",
                                        "mr_ci_lo", "mr_ci_hi"], e1)
    rounds = []
    for c in CONFIGS:
        w = [rng.random() for _ in range(20)]
        rounds += [[c, k, v / sum(w)] for k, v in enumerate(w, start=1)]
    _write(root, "sim/E2_rounds.csv", ["config", "round_count", "share"], rounds)
    _write(root, "sim/E2_end.csv", ["config", "matched", "ttl", "round_limit"],
           [[c, 0.7 + 0.03 * i, 0.25 - 0.03 * i, 0.05] for i, c in enumerate(CONFIGS)])
    _write(root, "sim/E3_fixed.csv", ["config", "mode", "match_rate", "ci_lo", "ci_hi", "time_to_match_median",
                                      "winner_eta_mean"],
           [[c, mode, 0.8 if mode == "bargain" else 0.6, 0.75, 0.85, 40.0 if mode == "bargain" else 8.0, 6.5]
            for c in CONFIGS for mode in ("bargain", "fixed")])
    _write(root, "sim/E4_heatmap.csv", ["config", "offer_ttl", "round_limit", "match_rate", "duration_median"],
           [[c, ttl, rl, 0.5 + 0.004 * ttl + 0.005 * rl, 30.0 + rl] for c in CONFIGS for ttl in (10, 20, 30, 60)
            for rl in (5, 10, 20, 40)])
    e7 = []
    for c in CONFIGS:
        for j, s in enumerate(("S1", "S2", "S3", "S4")):
            for share in (0.0, 0.1, 0.3, 0.5):
                d = share * (0.1 + 0.05 * j)
                e7.append([c, s, share, 1.1 + d, d, d - 0.02, d + 0.02, 1 - share])
    _write(root, "sim/E7_collusion.csv", ["config", "strategy", "ring_share", "markup_median", "delta_vs_0", "ci_lo",
                                          "ci_hi", "honest_win_share"], e7)


def collusion(root):
    for s in ("S4", "S5"):
        _write(root, f"collusion/T6_{s}.csv", ["method", "n", "pr_auc", "ci_lo", "ci_hi", "recall_at_thr", "fpr_at_thr",
                                               "fpr_at_recall80"],
               [["model", 300, 0.71, 0.65, 0.77, 0.6, 0.08, 0.15], ["B-price", 300, 0.45, 0.39, 0.51, 0.3, 0.05, 0.4],
                ["B-rule", 300, 0.55, 0.49, 0.61, 0.4, 0.07, 0.3]])
    _write(root, "collusion/F9_S4.csv", ["method", "ring_share", "n", "pr_auc", "ci_lo", "ci_hi"],
           [[m, share, 60, base + 0.1 * share, base + 0.1 * share - 0.05, base + 0.1 * share + 0.05]
            for m, base in (("model", 0.6), ("B-price", 0.4), ("B-rule", 0.5)) for share in (0.1, 0.3, 0.5, 0.7, 0.9)])


def pilot(root):
    _write(root, "pilot/pilot_summary.csv", ["n_deals", "n_matched", "rank1_share", "n_rank_gt1",
                                             "mean_extra_paid_ratio", "mean_eta_saved_min", "rider_picked_bid_share",
                                             "driver_took_offer_share"],
           [[36, 31, 0.71, 9, 0.04, 1.8, 0.81, 0.19]])


def write_fake(root, seed=0):
    root = os.path.abspath(root)
    if os.path.commonpath([root, REAL_RESULTS]) == REAL_RESULTS:
        raise ValueError(f"fake results never go under {REAL_RESULTS}")
    rng = random.Random(seed)
    model_a(root, rng)
    tables(root)
    sim(root, rng)
    collusion(root)
    pilot(root)
    return root


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python scripts/figures/fake_results.py <tmp dir>")
    print(write_fake(sys.argv[1]))
