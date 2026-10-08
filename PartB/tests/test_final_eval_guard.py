"""Card B6: the one-time test opening refuses to run twice or on changed inputs, and runs end to end on fake data.

Every test passes tmp paths for --data-dir and --results-dir (test mode), or points the defaults at tmp
paths, so the real results/model_a/TEST_OPENED.json is never written.
"""
import csv
import gzip
import json
import os

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from training import final_eval

REAL_OPENED = os.path.join(final_eval.ROOT, "results", "model_a", final_eval.OPENED_NAME)

# (route_set, route_id, stratum, distance_km, cells per block): U = number of blocks
ROUTES = [
    ("main", 0, "medium", 12.0, [3, 3, 3, 3]),
    ("main", 1, "short", 8.0, [4, 3, 3]),
    ("main", 2, "long", 25.0, [3, 3, 2, 3, 3]),
    ("main", 3, "short", 6.0, [4, 4]),            # U = 2: in no subset
    ("holdout", 0, "short", 9.0, [3, 4, 3]),
    ("holdout", 1, "medium", 14.0, [3, 3, 3, 3]),
]
DEPARTURES = ["2024-06-03T08:00", "2024-07-15T09:30", "2024-09-02T03:00", "2024-10-21T12:00",
              "2025-06-09T06:00", "2025-08-18T10:00"]


def route_row(route_set, route_id, stratum, km, blocks):
    cell = [1000 * (route_id + 1) + 10 * (route_set == "holdout") + b for b, n in enumerate(blocks) for _ in range(n)]
    P = len(cell)
    s = np.linspace(0.0, km, P)
    return {"route_set": route_set, "route_id": route_id, "stratum": stratum, "distance_km": km,
            "unique_cells": len(blocks), "cell": cell, "s_km": s.tolist(), "t_min": (s * 3.0).tolist()}


def write_fake_data(data_dir):
    rng = np.random.default_rng(0)
    routes = [route_row(*r) for r in ROUTES]
    for route_set, name in (("main", "routes.parquet"), ("holdout", "routes_holdout.parquet")):
        pq.write_table(pa.Table.from_pylist([r for r in routes if r["route_set"] == route_set]), data_dir / name)
    samples, sid = [], 0
    for r in routes:
        holdout = r["route_set"] == "holdout"
        for j in range(3 if holdout else 6):
            dep = DEPARTURES[(j + r["route_id"]) % len(DEPARTURES)]
            P = len(r["cell"])
            wet = j % 3 != 2
            gt = (rng.gamma(1.5, 1.2, P) * np.linspace(0.5, 1.5, P)) if wet else rng.uniform(0, 0.05, P)
            samples.append({
                "route_set": r["route_set"], "route_id": r["route_id"], "stratum": r["stratum"],
                "unique_cells": r["unique_cells"], "split": "test_holdout" if holdout else "test",
                "departure_utc": dep, "departure_local": dep, "season": "sw_monsoon", "wet": wet,
                "route_mean_mm": float(np.mean(gt)), "route_max_mm": float(np.max(gt)),
                "gt_mm": gt.tolist(), "sample_id": sid})
            sid += 1
    # Splits that must never be read.
    samples.append({**samples[0], "split": "train", "sample_id": sid})
    samples.append({**samples[1], "split": "val", "sample_id": sid + 1})
    pq.write_table(pa.Table.from_pylist(samples), data_dir / "samples.parquet")
    return sid


@pytest.fixture
def dirs(tmp_path):
    data_dir, results_dir = tmp_path / "data", tmp_path / "results"
    data_dir.mkdir()
    write_fake_data(data_dir)
    return data_dir, results_dir


def args(dirs, confirm=True):
    data_dir, results_dir = dirs
    return (["--confirm-open-test"] if confirm else []) + ["--data-dir", str(data_dir), "--results-dir", str(results_dir)]


@pytest.fixture(autouse=True)
def real_results_untouched():
    before = os.path.exists(REAL_OPENED)
    yield
    assert os.path.exists(REAL_OPENED) == before, "a test touched the real TEST_OPENED.json"


def test_without_the_confirm_flag_exits_2(dirs):
    assert final_eval.main([]) == 2
    assert final_eval.main(args(dirs, confirm=False)) == 2
    assert not dirs[1].exists()


def test_existing_opened_record_exits_2(dirs):
    dirs[1].mkdir()
    (dirs[1] / final_eval.OPENED_NAME).write_text("{}", encoding="utf-8")
    assert final_eval.main(args(dirs)) == 2
    assert sorted(os.listdir(dirs[1])) == [final_eval.OPENED_NAME]


@pytest.fixture
def real_mode(dirs, monkeypatch):
    """Defaults pointed at tmp paths: the checks run as in a real opening, git reports a clean tree."""
    monkeypatch.setattr(final_eval, "DEFAULT_DATA_DIR", str(dirs[0]))
    monkeypatch.setattr(final_eval, "DEFAULT_RESULTS_DIR", str(dirs[1]))
    monkeypatch.setattr(final_eval, "tracked_changes", lambda: [])
    return dirs


def test_sha_mismatch_exits_2(real_mode, tmp_path, monkeypatch):
    frozen = json.loads(open(final_eval.FROZEN_PATH, encoding="utf-8").read())
    frozen["gp_rt_sha256"] = "0" * 64
    path = tmp_path / "frozen.json"
    path.write_text(json.dumps(frozen), encoding="utf-8")
    monkeypatch.setattr(final_eval, "FROZEN_PATH", str(path))

    assert not final_eval.is_test_mode(final_eval.DEFAULT_DATA_DIR, final_eval.DEFAULT_RESULTS_DIR)
    assert final_eval.hash_mismatches() == ["gp_rt_sha256"]
    assert final_eval.main(["--confirm-open-test"]) == 2
    assert not real_mode[1].exists()


def test_dirty_tree_exits_2(real_mode, monkeypatch):
    monkeypatch.setattr(final_eval, "tracked_changes", lambda: [" M PartB/weather/gp.py"])
    assert final_eval.main(["--confirm-open-test"]) == 2
    monkeypatch.setattr(final_eval, "tracked_changes", lambda: None)       # git not available: fail closed
    assert final_eval.main(["--confirm-open-test"]) == 2
    assert not real_mode[1].exists()


def test_non_default_paths_are_test_mode(dirs):
    assert final_eval.is_test_mode(str(dirs[0]), final_eval.DEFAULT_RESULTS_DIR)
    assert final_eval.is_test_mode(final_eval.DEFAULT_DATA_DIR, str(dirs[1]))
    assert not final_eval.is_test_mode(final_eval.DEFAULT_DATA_DIR, final_eval.DEFAULT_RESULTS_DIR)


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def test_fake_data_runs_end_to_end_and_only_once(dirs):
    data_dir, results_dir = dirs
    assert final_eval.main(args(dirs)) == 0

    opened = json.loads((results_dir / final_eval.OPENED_NAME).read_text(encoding="utf-8"))
    assert list(opened) == ["opened_utc", "git_head", "frozen_sha256"]
    assert set(opened["frozen_sha256"]) == set(final_eval.HASHED)

    for name, columns in final_eval.COLUMNS.items():
        table = read_csv(results_dir / name)
        assert tuple(table[0]) == columns, name
        assert len(table) > 1, f"{name} has no rows"

    with gzip.open(results_dir / "test_per_sample.csv.gz", "rt", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert tuple(rows[0]) == final_eval.PER_SAMPLE_COLUMNS
    assert {r["split"] for r in rows} == {"test", "test_holdout"}                 # train/val never read
    assert len({r["sample_id"] for r in rows}) == 30
    assert {r["method"] for r in rows} == {"B0", "B1", "B1-L", "B2", "B2-L", "M1", "M2"}
    # k_abs rows only up to U; rho rows use the budget rule.
    assert all(int(r["k"]) <= int(r["U"]) for r in rows if r["rho"] == "")
    # R-T: M1/M2 rows with the main model never count for RT; the extra rows count only for RT.
    gp_rt = [r for r in rows if r["method"] in ("M1", "M2") and "RT" in r["subset_flags"]]
    assert gp_rt and all(r["subset_flags"] == "RT" for r in gp_rt)
    assert any("RT" in r["subset_flags"] for r in rows if r["method"] == "B1")
    # U = 2 route: computed but in no subset.
    assert {r["subset_flags"] for r in rows if r["route_set"] == "main" and r["route_id"] == "3"} == {""}

    t1 = read_csv(results_dir / "T1_table.csv")
    assert {row[0] for row in t1[1:]} == {"MAIN", "ALL", "LONG", "HOLDOUT", "RT"}
    b1_main = next(row for row in t1[1:] if row[0] == "MAIN" and row[1] == "B1")
    assert b1_main[-1] == "0.000000"                                            # B1 against itself
    assert len(read_csv(results_dir / "stats_tests.csv")) == 1 + 4 * 3

    summary = json.loads((results_dir / "summary.json").read_text(encoding="utf-8"))
    assert set(summary) == {"n_test_main", "n_holdout_main", "n_weeks_main", "headline"}
    assert set(summary["headline"]) == {"mae_rho50", "saving_vs_B1", "b1_duplicate_rate_rho100",
                                        "m1_cov_points_rho50"}
    assert set(summary["headline"]["mae_rho50"]) == {"M1", "B1", "B2-L", "M2"}
    assert summary["n_test_main"] == 12 and summary["n_holdout_main"] == 4

    before = sorted(os.listdir(results_dir))
    assert final_eval.main(args(dirs)) == 2                                     # second opening refused
    assert sorted(os.listdir(results_dir)) == before
