"""paper-revision-v1 X1: the post-hoc placement rules and the comparison script on fake data.

The end-to-end test opens a fake test split with final_eval in test mode (tmp paths only), so the real
results/model_a/ is never written.
"""
import csv
import gzip
import json
import os

import numpy as np
import pytest

from test_final_eval_guard import write_fake_data
from training import final_eval, posthoc_placement as ph
from weather.oracle import RouteOracle
from weather.selection import select_b2

RULE_CALLS = {name: ph.RULES[name] for name in ph.RULE_NAMES}


def oracle_of(cells):
    return RouteOracle(np.array(cells), np.zeros(len(cells)))


def blocks(sizes):
    return [c + 1 for c, n in enumerate(sizes) for _ in range(n)]


def test_every_rule_returns_k_distinct_cells():
    rng = np.random.default_rng(0)
    for U in range(1, 11):
        cells = blocks(rng.integers(1, 5, U))
        o = oracle_of(cells)
        s = np.linspace(0.0, 3.0 * U, len(cells))
        for k in range(1, U + 1):
            for name, rule in RULE_CALLS.items():
                chosen = rule(o, s, k, 7)
                assert len(chosen) == k and len(set(chosen)) == k, (name, U, k)
                assert set(chosen) <= set(o.order)


def test_cell_centred_indices():
    order = [10, 11, 12, 13, 14]
    assert ph.select_hc(order[:4], 2) == [11, 13]
    assert ph.select_hc(order[:3], 2) == [10, 12]
    assert ph.select_hc(order, 1) == [12]


def test_point_centred_rule_and_its_collision_fallback():
    assert ph.select_hp(oracle_of([1, 1, 1, 2, 2, 3, 3, 3, 3, 4]), 2) == [1, 3]
    # both centre points (2 and 7) fall in cell 1: the second goes to the cell with the closest point (8 -> cell 2)
    assert ph.select_hp(oracle_of([1] * 8 + [2, 3]), 2) == [1, 2]


def test_anchored_rules_start_from_m2_anchor():
    o = oracle_of(blocks([2, 3, 1, 4, 2, 3]))
    s = np.arange(len(o.cell), dtype=float)
    for k in range(1, o.U + 1):
        start = list(select_b2(o.order, -(-k // 2)))
        for name in ("H-R", "H-N", "H-D", "H-S"):
            assert RULE_CALLS[name](o, s, k, 3)[:len(start)] == start, (name, k)


def test_count_distance_and_distance_sum_by_hand():
    # cells 1..4 with 3, 2, 4, 1 points at s = 0..9; k = 3 -> anchor = first and last cell (1, 4).
    # d: s3 1, s4 2, s5 3, s6 3, s7 2, s8 1 -> cell 2: min 1, sum 3; cell 3: min 1, sum 9.
    o = oracle_of([1, 1, 1, 2, 2, 3, 3, 3, 3, 4])
    s = np.arange(10, dtype=float)
    assert RULE_CALLS["H-N"](o, s, 3, 0) == [1, 4, 3]       # 4 points beat 2
    assert RULE_CALLS["H-D"](o, s, 3, 0) == [1, 4, 2]       # tie at 1: first cell wins
    assert RULE_CALLS["H-S"](o, s, 3, 0) == [1, 4, 3]       # 9 beats 3
    # k = 2 -> anchor = middle cell (3); cell 1 is farthest (min 3, sum 12) and has the most points
    for name in ("H-N", "H-D", "H-S"):
        assert RULE_CALLS[name](o, s, 2, 0) == [3, 1]


def test_count_rule_breaks_ties_by_route_order():
    o = oracle_of([1, 1, 2, 2, 3, 3, 4, 4, 5])
    assert RULE_CALLS["H-N"](o, np.arange(9.0), 3, 0) == [1, 5, 2]


def test_random_rule_is_seeded_by_sample_and_budget():
    o = oracle_of(blocks([1] * 10))
    s = np.arange(10.0)
    assert ph.select_hr(o, 6, 5) == ph.select_hr(o, 6, 5)
    draws = {tuple(ph.select_hr(o, 6, sid)) for sid in range(20)}
    assert len(draws) > 1


def test_rules_ignore_values():
    cells = blocks([3, 2, 4, 1, 3])
    s = np.linspace(0, 12, len(cells))
    a = RouteOracle(np.array(cells), np.zeros(len(cells)))
    b = RouteOracle(np.array(cells), np.random.default_rng(1).gamma(1.0, 2.0, len(cells)))
    for k in range(1, 6):
        for name, rule in RULE_CALLS.items():
            assert rule(a, s, k, 9) == rule(b, s, k, 9), (name, k)


@pytest.fixture
def opened(tmp_path):
    """A fake test split opened once by final_eval in test mode: (data_dir, frozen_dir)."""
    data_dir, frozen_dir = tmp_path / "data", tmp_path / "frozen"
    data_dir.mkdir()
    write_fake_data(data_dir)
    assert final_eval.main(["--confirm-open-test", "--data-dir", str(data_dir), "--results-dir", str(frozen_dir)]) == 0
    return data_dir, frozen_dir


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def test_fake_data_runs_end_to_end(opened, tmp_path):
    data_dir, frozen_dir = opened
    out = tmp_path / "out"
    argv = ["--data-dir", str(data_dir), "--frozen-dir", str(frozen_dir), "--out-dir", str(out)]
    assert ph.main(argv) == 0

    assert sorted(os.listdir(out)) == sorted(["placement_per_sample.csv.gz", "summary.json", *ph.COLUMNS])
    for name, columns in ph.COLUMNS.items():
        table = read_csv(out / name)
        assert tuple(table[0]) == columns, name
    with gzip.open(out / "placement_per_sample.csv.gz", "rt", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert tuple(rows[0]) == ph.PER_SAMPLE_COLUMNS
    assert {r["method"] for r in rows} == set(ph.METHODS)
    assert {r["subset"] for r in rows} == {"MAIN", "HOLDOUT"}
    assert all(r["same_as_m2"] == "1" for r in rows if r["method"] == "M2")
    assert all(r["cells"] == "" for r in rows if r["method"] == "B1")
    assert len(read_csv(out / "placement_tests.csv")) == 1 + 24
    assert len(read_csv(out / "placement_mae.csv")) == 1 + 2 * len(ph.METHODS) * 3

    saving = {r[0]: r for r in read_csv(out / "placement_saving.csv")[1:]}
    frozen_t1 = {r[1]: r for r in read_csv(frozen_dir / "T1_table.csv")[1:] if r[0] == "MAIN"}
    assert saving["M2"][2] == frozen_t1["M2"][-1]                               # same saving as final_eval

    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["reproduction_checked_rows"] == 3 * 3 * 16                   # B1/M1/M2 x 3 rho x 16 samples
    assert summary["reproduction_max_abs_diff"] <= ph.TOL

    before = (out / "placement_mae.csv").read_bytes()
    assert ph.main(argv) == 0
    assert (out / "placement_mae.csv").read_bytes() == before                   # deterministic


def test_reproduction_failure_writes_nothing(opened, tmp_path):
    data_dir, frozen_dir = opened
    path = frozen_dir / "test_per_sample.csv.gz"
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    target = next(i for i, r in enumerate(rows[1:], 1)
                  if r[header.index("method")] == "M2" and r[header.index("rho")] == "0.5"
                  and "MAIN" in r[header.index("subset_flags")])
    col = header.index("abs_err")
    rows[target][col] = f"{float(rows[target][col]) + 0.01:.6f}"
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        csv.writer(f, lineterminator="\n").writerows(rows)

    out = tmp_path / "out"
    assert ph.main(["--data-dir", str(data_dir), "--frozen-dir", str(frozen_dir), "--out-dir", str(out)]) == 3
    assert not out.exists()
