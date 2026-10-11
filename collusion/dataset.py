"""Joins features with labels (card D2). This is the only module that reads labels.csv."""

from __future__ import annotations

import csv
import os

import numpy as np

from collusion.features import build_features


def load_labels(labels_csv: str) -> dict[tuple[str, str], tuple[int, str]]:
    """(run_id, driver_id) -> (is_colluder, strategy)."""
    out: dict[tuple[str, str], tuple[int, str]] = {}
    with open(labels_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[(row["run_id"], row["driver_id"])] = (int(row["is_colluder"]), row["strategy"])
    return out


def parse_run_id(run_id: str) -> tuple[str, float]:
    """'S1-r0.3-s7' -> ('S1', 0.3): the strategy and ring share the run was generated with."""
    strategy, share, _ = run_id.split("-")
    if not share.startswith("r"):
        raise ValueError(f"unexpected run_id: {run_id}")
    return strategy, float(share[1:])


def build_dataset(strategy_dirs: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Features and labels of every (run, driver) under the given raw output folders.

    Each folder holds one strategy's actions.csv, deals_out.csv and labels.csv.
    Returns (keys [n, 2] of run_id and driver_id, X [n, len(FEATURES)], y [n], strategy_of_run [n],
    ring_share_of_run [n]). Every labelled driver must have a feature row and the reverse.
    """
    keys: list[tuple[str, str]] = []
    blocks: list[np.ndarray] = []
    y: list[int] = []
    strategies: list[str] = []
    shares: list[float] = []
    for d in strategy_dirs:
        k, X = build_features(os.path.join(d, "actions.csv"), os.path.join(d, "deals_out.csv"))
        labels = load_labels(os.path.join(d, "labels.csv"))
        missing = set(labels) - set(k)
        unlabelled = set(k) - set(labels)
        if missing or unlabelled:
            raise ValueError(f"{d}: {len(missing)} labelled drivers without features, "
                             f"{len(unlabelled)} feature rows without a label")
        for key in k:
            strategy, share = parse_run_id(key[0])
            keys.append(key)
            y.append(labels[key][0])
            strategies.append(strategy)
            shares.append(share)
        blocks.append(X)
    X_all = np.vstack(blocks) if blocks else np.empty((0, 0))
    return (np.asarray(keys, dtype=str).reshape(len(keys), 2), X_all, np.asarray(y, dtype=int),
            np.asarray(strategies, dtype=str), np.asarray(shares, dtype=float))
