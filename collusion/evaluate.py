"""One-time evaluation of the frozen model on an unseen strategy (ml-design v5 §7.5, card D4).

Run from the repository root, once per strategy, by a person:
    python -m collusion.evaluate --holdout S4 --confirm-open
    python -m collusion.evaluate --holdout S5 --confirm-open

Start checks (exit code 2 on failure): --confirm-open given; no HOLDOUT_OPENED_<strategy>.json yet;
the three raw files exist; model.pkl matches model_sha256 of collusion_frozen.json; no change in
git-tracked files. Then HOLDOUT_OPENED_<strategy>.json is written before anything is computed.

With a non-default --raw-dir or --results-dir the script runs in test mode: the frozen config is
read from <results-dir>/collusion_frozen.json and the hash and git checks are skipped.

Methods and decisions (score > threshold flags a driver):
- model: predict_proba[:, 1] of the frozen model, threshold from collusion_frozen.json.
- B-price: price-outlier z (collusion.baselines), flagged when z > 2.
- B-rule: sign × the frozen best single feature, threshold from collusion_frozen.json.
CIs: percentile bootstrap over seeds (B = 2000, numpy default_rng(42)); a resampled seed brings
all of its runs. The same resamples serve every method.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import pickle
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np
from sklearn.metrics import average_precision_score, roc_curve

from collusion.baselines import price_outlier_scores
from collusion.dataset import build_dataset
from collusion.features import FEATURES

RAW_DIR = os.path.join("results", "sim", "raw", "collusion")
RESULTS_DIR = os.path.join("results", "collusion")
FROZEN = os.path.join("collusion", "configs", "collusion_frozen.json")
HOLDOUTS = ("S4", "S5")
RAW_FILES = ("actions.csv", "deals_out.csv", "labels.csv")
B_PRICE_Z = 2.0
BOOTSTRAP_B = 2000
BOOTSTRAP_SEED = 42
RECALL_TARGET = 0.8
METHODS = ("model", "B-price", "B-rule")


class GuardError(Exception):
    """A start check failed; nothing was opened."""


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def opened_path(results_dir: str, holdout: str) -> str:
    return os.path.join(results_dir, f"HOLDOUT_OPENED_{holdout}.json")


def check(holdout: str, confirm: bool, raw_dir: str, results_dir: str, frozen_path: str, strict: bool,
          tracked_changes=lambda: git("status", "--porcelain", "--untracked-files=no").strip()) -> dict:
    """All start checks; returns the frozen config. Raises GuardError on the first failure."""
    if not confirm:
        raise GuardError("--confirm-open is required: the holdout can be opened only once")
    if os.path.exists(opened_path(results_dir, holdout)):
        raise GuardError(f"{holdout} was already opened: {opened_path(results_dir, holdout)}")
    for f in RAW_FILES:
        if not os.path.exists(os.path.join(raw_dir, holdout, f)):
            raise GuardError(f"missing {os.path.join(raw_dir, holdout, f)}")
    with open(frozen_path, encoding="utf-8") as f:
        frozen = json.load(f)
    if frozen.get("features") != FEATURES:
        raise GuardError("feature list differs from collusion_frozen.json")
    if strict:
        model = os.path.join(results_dir, "model.pkl")
        if sha256_file(model) != frozen["model_sha256"]:
            raise GuardError("model.pkl does not match model_sha256 in collusion_frozen.json")
        changes = tracked_changes()
        if changes:
            raise GuardError("git-tracked files have changes:\n" + changes)
    return frozen


def write_opened(holdout: str, raw_dir: str, results_dir: str, frozen_path: str, strict: bool) -> None:
    record = {
        "opened_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "holdout": holdout,
        "git_head": git("rev-parse", "HEAD").strip() if strict else "test-mode",
        "model_sha256": sha256_file(os.path.join(results_dir, "model.pkl")),
        "frozen_sha256": sha256_file(frozen_path),
        "data_sha256": {f: sha256_file(os.path.join(raw_dir, holdout, f)) for f in RAW_FILES},
    }
    os.makedirs(results_dir, exist_ok=True)
    with open(opened_path(results_dir, holdout), "x", encoding="utf-8", newline="\n") as f:
        json.dump(record, f, indent=2)
        f.write("\n")


def fpr_at_recall(y: np.ndarray, score: np.ndarray, target: float = RECALL_TARGET) -> float:
    """Lowest FPR among thresholds whose recall is at least target."""
    fpr, tpr, _ = roc_curve(y, score)
    return float(fpr[np.argmax(tpr >= target)])


def bootstrap_ci(y: np.ndarray, scores: dict[str, np.ndarray], seed_of_row: np.ndarray,
                 rng: np.random.Generator, b: int = BOOTSTRAP_B) -> dict[str, tuple[float, float]]:
    """Percentile 95% CI of PR-AUC per method, resampling seeds with replacement (paired)."""
    seeds = np.unique(seed_of_row)
    rows = {s: np.flatnonzero(seed_of_row == s) for s in seeds}
    stats = {m: np.empty(b) for m in scores}
    for i in range(b):
        idx = np.concatenate([rows[s] for s in rng.choice(seeds, size=len(seeds), replace=True)])
        for m, sc in scores.items():
            stats[m][i] = average_precision_score(y[idx], sc[idx]) if y[idx].any() else np.nan
    return {m: (float(np.nanpercentile(v, 2.5)), float(np.nanpercentile(v, 97.5))) for m, v in stats.items()}


def evaluate(holdout: str, raw_dir: str, results_dir: str, frozen: dict) -> dict:
    """Scores the three methods and writes T6_<holdout>.csv and F9_<holdout>.csv."""
    d = os.path.join(raw_dir, holdout)
    keys, X, y, strategy, share = build_dataset([d])
    if set(strategy.tolist()) != {holdout}:
        raise ValueError(f"{d} holds runs of {sorted(set(strategy.tolist()))}, expected {holdout}")
    seed = np.array([int(run.rsplit("-s", 1)[1]) for run in keys[:, 0]])

    with open(os.path.join(results_dir, "model.pkl"), "rb") as f:
        model = pickle.load(f)
    z = price_outlier_scores(os.path.join(d, "deals_out.csv"), os.path.join(d, "actions.csv"))
    rule = FEATURES.index(frozen["best_single_feature"])
    scores = {
        "model": model.predict_proba(X)[:, 1],
        "B-price": np.array([z[(r, drv)] for r, drv in keys]),
        "B-rule": frozen["best_single_sign"] * X[:, rule],
    }
    thresholds = {"model": frozen["threshold"], "B-price": B_PRICE_Z, "B-rule": frozen["best_single_threshold"]}

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    t6 = []
    ci = bootstrap_ci(y, scores, seed, rng)
    for m in METHODS:
        flagged = scores[m] > thresholds[m]
        t6.append({"method": m, "n": len(y), "pr_auc": average_precision_score(y, scores[m]),
                   "ci_lo": ci[m][0], "ci_hi": ci[m][1],
                   "recall_at_thr": float(flagged[y == 1].mean()), "fpr_at_thr": float(flagged[y == 0].mean()),
                   "fpr_at_recall80": fpr_at_recall(y, scores[m])})
    f9 = []
    for s in sorted(set(share.tolist())):
        rows = share == s
        ci_s = bootstrap_ci(y[rows], {m: v[rows] for m, v in scores.items()}, seed[rows], rng)
        for m in METHODS:
            f9.append({"method": m, "ring_share": s, "n": int(rows.sum()),
                       "pr_auc": average_precision_score(y[rows], scores[m][rows]),
                       "ci_lo": ci_s[m][0], "ci_hi": ci_s[m][1]})

    write_csv(os.path.join(results_dir, f"T6_{holdout}.csv"), t6,
              ["method", "n", "pr_auc", "ci_lo", "ci_hi", "recall_at_thr", "fpr_at_thr", "fpr_at_recall80"])
    write_csv(os.path.join(results_dir, f"F9_{holdout}.csv"), f9,
              ["method", "ring_share", "n", "pr_auc", "ci_lo", "ci_hi"])
    return {"t6": t6, "f9": f9, "positives": int(y.sum())}


def write_csv(path: str, rows: list[dict], columns: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(columns)
        for r in rows:
            w.writerow([f"{r[c]:.6f}" if isinstance(r[c], float) else r[c] for c in columns])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Open one unseen collusion strategy, once.")
    ap.add_argument("--holdout", required=True, choices=HOLDOUTS)
    ap.add_argument("--confirm-open", action="store_true")
    ap.add_argument("--raw-dir", default=RAW_DIR)
    ap.add_argument("--results-dir", default=RESULTS_DIR)
    args = ap.parse_args(argv)

    strict = os.path.normpath(args.raw_dir) == os.path.normpath(RAW_DIR) and \
        os.path.normpath(args.results_dir) == os.path.normpath(RESULTS_DIR)
    frozen_path = FROZEN if strict else os.path.join(args.results_dir, "collusion_frozen.json")
    try:
        frozen = check(args.holdout, args.confirm_open, args.raw_dir, args.results_dir, frozen_path, strict)
    except GuardError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    write_opened(args.holdout, args.raw_dir, args.results_dir, frozen_path, strict)

    out = evaluate(args.holdout, args.raw_dir, args.results_dir, frozen)
    print(f"{args.holdout}{'' if strict else ' (test mode)'}: n={out['t6'][0]['n']} positives={out['positives']}")
    for r in out["t6"]:
        print(f"  {r['method']:8s} PR-AUC={r['pr_auc']:.4f} [{r['ci_lo']:.4f}, {r['ci_hi']:.4f}] "
              f"recall@thr={r['recall_at_thr']:.4f} fpr@thr={r['fpr_at_thr']:.4f} fpr@recall80={r['fpr_at_recall80']:.4f}")
    if args.holdout == "S4":
        m, p = (next(r["pr_auc"] for r in out["t6"] if r["method"] == k) for k in ("model", "B-price"))
        print(f"  gate (ml-design v5 §7.5): model PR-AUC {m:.4f} {'>' if m > p else '<='} B-price {p:.4f} -> "
              f"{'PASS' if m > p else 'FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
