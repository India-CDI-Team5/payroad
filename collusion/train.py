"""Strategy-wise cross-validation and freeze (ml-design v5 §7.4, card D3).

Run from the repository root: python -m collusion.train
Reads results/collusion/features_train.npz (S1~S3 only) and writes results/collusion/loso.csv,
results/collusion/model.pkl and collusion/configs/collusion_frozen.json. The frozen file is not
overwritten unless --refreeze is given: after it exists, S4 and S5 may be generated.

Threshold rule (model and B-rule alike): a row is flagged when its score is strictly greater
than the threshold. The threshold is the score of the (k + 1)-th highest negative, k = floor(1% ×
negatives), over the pooled validation predictions, so at most 1% of negatives are flagged.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import pickle
import sys
from datetime import datetime, timezone

import numpy as np
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from collusion.baselines import best_single_feature
from collusion.features import FEATURES

DATA = os.path.join("results", "collusion", "features_train.npz")
LOSO = os.path.join("results", "collusion", "loso.csv")
MODEL = os.path.join("results", "collusion", "model.pkl")
FROZEN = os.path.join("collusion", "configs", "collusion_frozen.json")
COLLUSION_PARAMS = os.path.join("data", "experiment", "collusion-params.json")

# (training strategies, held-out strategy), in the order of the card
FOLDS = ((("S1", "S2"), "S3"), (("S1", "S3"), "S2"), (("S2", "S3"), "S1"))
TIE = 0.005
FPR = 0.01


def candidates() -> dict:
    """The five pre-registered candidates: LR, then HGB × learning_rate × max_iter."""
    out = {"LR": make_pipeline(StandardScaler(),
                               LogisticRegression(C=1.0, class_weight="balanced", max_iter=1000))}
    for lr in (0.05, 0.1):
        for it in (200, 400):
            out[f"HGB-lr{lr}-it{it}"] = HistGradientBoostingClassifier(
                max_depth=3, l2_regularization=1.0, class_weight="balanced", random_state=42,
                learning_rate=lr, max_iter=it)
    return out


def strategy_folds(strategy: np.ndarray) -> list[tuple[str, np.ndarray, np.ndarray]]:
    """(held-out strategy, train rows, validation rows) for the three folds."""
    out = []
    for train, held in FOLDS:
        tr = np.flatnonzero(np.isin(strategy, train))
        va = np.flatnonzero(strategy == held)
        if len(tr) == 0 or len(va) == 0:
            raise ValueError(f"fold {train} -> {held} has no rows")
        out.append((held, tr, va))
    return out


def select(means: dict[str, float]) -> str:
    """Highest mean PR-AUC; LR whenever it is within TIE of the best. Exact ties keep the first name."""
    best = max(means, key=lambda name: means[name])
    if "LR" in means and means["LR"] >= means[best] - TIE:
        return "LR"
    return best


def fpr_threshold(score: np.ndarray, y: np.ndarray, fpr: float = FPR) -> float:
    """Threshold t such that flagging score > t flags at most fpr of the negatives (see module doc)."""
    neg = np.sort(score[y == 0])[::-1]
    if len(neg) == 0:
        raise ValueError("no negatives")
    k = int(np.floor(fpr * len(neg)))
    return float(neg[min(k, len(neg) - 1)])


def cross_validate(X: np.ndarray, y: np.ndarray, strategy: np.ndarray):
    """Per candidate: fold PR-AUCs by held-out strategy and the pooled out-of-fold scores."""
    folds = strategy_folds(strategy)
    results = {}
    for name, model in candidates().items():
        oof = np.full(len(y), np.nan)
        per_fold = {}
        for held, tr, va in folds:
            m = clone(model).fit(X[tr], y[tr])
            oof[va] = m.predict_proba(X[va])[:, 1]
            per_fold[held] = float(average_precision_score(y[va], oof[va]))
        results[name] = (per_fold, oof)
    return folds, results


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refreeze", action="store_true", help="overwrite an existing collusion_frozen.json")
    args = ap.parse_args(argv)
    if os.path.exists(FROZEN) and not args.refreeze:
        print(f"{FROZEN} already exists (frozen). Use --refreeze only before S4/S5 are generated.", file=sys.stderr)
        return 2

    d = np.load(DATA)
    X, y, strategy = d["X"], d["y"], d["strategy"]
    if sorted(set(strategy.tolist())) != ["S1", "S2", "S3"]:
        raise ValueError(f"training data must be exactly S1~S3: {sorted(set(strategy.tolist()))}")
    if X.shape[1] != len(FEATURES):
        raise ValueError(f"{X.shape[1]} feature columns, expected {len(FEATURES)}")

    folds, results = cross_validate(X, y, strategy)
    means = {name: float(np.mean(list(per.values()))) for name, (per, _) in results.items()}
    selected = select(means)
    threshold = fpr_threshold(results[selected][1], y)

    plain_folds = [(tr, va) for _, tr, va in folds]
    single, sign = best_single_feature(X, y, plain_folds)
    single_threshold = fpr_threshold(sign * X[:, FEATURES.index(single)], y)

    final = clone(candidates()[selected]).fit(X, y)
    os.makedirs(os.path.dirname(MODEL), exist_ok=True)
    with open(MODEL, "wb") as f:
        pickle.dump(final, f)

    with open(LOSO, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["candidate", "held_out", "pr_auc"])
        for name, (per, _) in results.items():
            for held, _, _ in folds:
                w.writerow([name, held, f"{per[held]:.6f}"])

    frozen = {
        "frozen_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "features": FEATURES,
        "selected": selected,
        "candidates": [{"name": name, "fold_pr_auc": per, "mean": means[name]} for name, (per, _) in results.items()],
        "threshold": threshold,
        "threshold_rule": "flag when score > threshold; score = predict_proba[:, 1] (model) or sign * feature (B-rule)",
        "model_sha256": sha256_file(MODEL),
        "best_single_feature": single,
        "best_single_sign": sign,
        "best_single_threshold": single_threshold,
        "collusion_params_sha256": sha256_file(COLLUSION_PARAMS),
    }
    os.makedirs(os.path.dirname(FROZEN), exist_ok=True)
    with open(FROZEN, "w", encoding="utf-8", newline="\n") as f:
        json.dump(frozen, f, indent=2, ensure_ascii=False)
        f.write("\n")

    for name, (per, _) in results.items():
        print(f"{name:18s} " + " ".join(f"{h}={per[h]:.4f}" for h, _, _ in folds) + f"  mean={means[name]:.4f}")
    oof = results[selected][1]
    print(f"selected={selected} threshold={threshold:.6f} "
          f"(oof recall={np.mean(oof[y == 1] > threshold):.4f}, fpr={np.mean(oof[y == 0] > threshold):.4f})")
    s = sign * X[:, FEATURES.index(single)]
    print(f"B-rule={single} sign={sign:+d} threshold={single_threshold:.6f} "
          f"(recall={np.mean(s[y == 1] > single_threshold):.4f}, fpr={np.mean(s[y == 0] > single_threshold):.4f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
