"""Baselines of ml-design v5 §7.5 (card D3): B-price (price outlier) and B-rule (best single feature)."""

from __future__ import annotations

import csv
from collections import defaultdict

import numpy as np
from sklearn.metrics import average_precision_score

from collusion.features import FEATURES

BIDS = ("BID_PLACE", "BID_UPDATE")


def price_outlier_scores(deals_csv: str, actions_csv: str) -> dict[tuple[str, str], float]:
    """B-price: (run_id, driver_id) -> z.

    For each driver, the mean over the deals it bid in of (its last accepted bid / base_price);
    then a z-score among the drivers of the same run that bid (population std). A driver that
    appeared but never bid, or a run whose drivers all have the same mean, gets 0.
    """
    base: dict[tuple[str, str], float] = {}
    with open(deals_csv, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        r, d, b = (header.index(c) for c in ("run_id", "deal_id", "base_price"))
        for row in reader:
            base[(row[r], row[d])] = float(row[b])

    last: dict[tuple[str, str, str], float] = {}  # (run, deal, driver) -> last accepted bid
    present: dict[str, set[str]] = defaultdict(set)
    with open(actions_csv, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        c = {n: header.index(n) for n in ("run_id", "deal_id", "actor_type", "driver_id", "action", "price", "accepted")}
        for row in reader:
            if row[c["actor_type"]] != "DRIVER":
                continue
            run, deal, driver, action = row[c["run_id"]], row[c["deal_id"]], row[c["driver_id"]], row[c["action"]]
            if action == "PRESENT":
                present[run].add(driver)
            elif action in BIDS and row[c["accepted"]] == "1":
                last[(run, deal, driver)] = float(row[c["price"]])

    ratios: dict[tuple[str, str], list[float]] = defaultdict(list)
    for (run, deal, driver), price in last.items():
        ratios[(run, driver)].append(price / base[(run, deal)])

    out: dict[tuple[str, str], float] = {}
    for run, drivers in present.items():
        means = {d: float(np.mean(ratios[(run, d)])) for d in drivers if (run, d) in ratios}
        values = np.array(list(means.values()))
        mu, sd = (float(values.mean()), float(values.std())) if len(values) else (0.0, 0.0)
        for d in drivers:
            out[(run, d)] = (means[d] - mu) / sd if d in means and sd > 0 else 0.0
    return out


def fold_pr_auc(score: np.ndarray, y: np.ndarray, folds: list[tuple[np.ndarray, np.ndarray]]) -> float:
    """Mean over folds of the PR-AUC of a fixed score on each fold's validation rows."""
    return float(np.mean([average_precision_score(y[val], score[val]) for _, val in folds]))


def best_single_feature(X: np.ndarray, y: np.ndarray, folds: list[tuple[np.ndarray, np.ndarray]]) -> tuple[str, int]:
    """B-rule: the feature and sign (+1 or -1) whose score sign × x has the highest mean
    validation PR-AUC over the folds. A single feature needs no fitting, so only the validation
    rows of each fold are used. Ties keep the first feature in FEATURES order, + before −.
    """
    best: tuple[float, str, int] | None = None
    for j, name in enumerate(FEATURES):
        for sign in (1, -1):
            ap = fold_pr_auc(sign * X[:, j], y, folds)
            if best is None or ap > best[0]:
                best = (ap, name, sign)
    assert best is not None
    return best[1], best[2]
