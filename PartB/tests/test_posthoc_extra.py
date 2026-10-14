"""paper-revision-v1 X15: post-hoc extras (previous system's queries, MAE by k, surcharge kappa) on small data."""
import csv
import gzip

import numpy as np
import pytest

from sampler import determine_sample_count
from training import posthoc_extra as px
from weather.interpolate import nearest_fill
from weather.oracle import RouteOracle


def test_sample_count_matches_the_previous_sampler():
    for d in (0.5, 9.99, 10, 29.9, 30, 59.9, 60, 120):
        assert px.sample_count(d) == determine_sample_count(d)


def test_previous_rows_use_both_ends_and_the_nearest_value():
    cells = np.array([1] * 5 + [2] * 5 + [3] * 5 + [4] * 5)
    y = np.repeat([1.0, 0.0, 0.0, 3.0], 5)
    case = {"flags": {"MAIN"}, "week": "2025-W01", "route": {"distance_km": 9.5}, "y": y,
            "oracle": RouteOracle(cells, y), "s": np.arange(20) * 0.5, "t": np.arange(20.0)}
    (subset, week, n, ncells, err), = px.previous_rows([case])
    assert (subset, n, ncells) == ("MAIN", 4, 4)                 # 4 points at index 0, 6, 13, 19: four cells
    idx = np.array([0, 6, 13, 19])
    assert err == pytest.approx(abs(np.mean(nearest_fill(case["s"], idx, y[idx])) - y.mean()))


def test_kappa_row():
    r = px.kappa_row("X", [1, 1, 0, 0, 0, 0, 0, 0, 0, 0], [1, 0, 0, 0, 0, 0, 0, 0, 0, 1])
    assert (r["base_rate"], r["agreement"], r["recall"], r["precision"]) == (0.2, 0.8, 0.5, 0.5)
    assert r["kappa"] == pytest.approx((0.8 - 0.68) / 0.32)


def test_kbin_table(tmp_path):
    path = tmp_path / "p.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["subset", "rho", "k", "method", "abs_err"])
        w.writerows([["MAIN", "0.5", 2, "M2", 0.1], ["MAIN", "0.5", 2, "M2", 0.3], ["MAIN", "0.5", 4, "M2", 0.2],
                     ["MAIN", "0.5", 3, "H-P", 0.4], ["MAIN", "0.5", 1, "H-C", 9.0]])
    rows = px.kbin_table(path)
    got = {(r["k_bin"], r["method"]): (r["n"], r["mae"]) for r in rows}
    assert got == {("2", "M2"): (2, pytest.approx(0.2)), (">=3", "M2"): (1, 0.2), (">=3", "H-P"): (1, 0.4)}


def test_previous_cell_rows_query_each_touched_cell_once():
    cells = np.array([1] * 5 + [2] * 5 + [3] * 5 + [4] * 5)
    y = np.repeat([1.0, 0.0, 0.0, 3.0], 5)
    case = {"flags": {"HOLDOUT"}, "week": "2025-W01", "route": {"distance_km": 9.5}, "y": y,
            "oracle": RouteOracle(cells, y), "s": np.arange(20) * 0.5, "t": np.arange(20.0)}
    (subset, week, calls, ncells, err), = px.previous_cell_rows([case])
    assert (subset, calls, ncells) == ("HOLDOUT", 4, 4)
    assert err == pytest.approx(0.0)                             # all four cells revealed: the full query
