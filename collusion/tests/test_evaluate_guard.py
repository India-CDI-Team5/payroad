"""Card D4 checks on fake data in tmp paths only: start guards, the one-time opening record, outputs."""

from __future__ import annotations

import csv
import json
import os
import pickle

import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression

from collusion import evaluate
from collusion.features import FEATURES

SEEDS = (101, 102, 103)
SHARES = (0.2, 0.5)
POOL = 10
PER_DEAL = 5
DEALS = 30


def fake_raw(raw_dir, holdout="S4"):
    """Colluders (the first round(share × POOL) drivers) bid once and never concede; others concede."""
    d = raw_dir / holdout
    d.mkdir(parents=True)
    rng = np.random.default_rng(0)
    actions = [["run_id", "deal_id", "t_sec", "actor_type", "driver_id", "action", "price", "accepted", "reject_code"]]
    deals = [["run_id", "deal_id", "base_price", "duration_sec", "winner_id", "winner_is_colluder"]]
    labels = [["run_id", "driver_id", "is_colluder", "strategy"]]
    for seed in SEEDS:
        for share in SHARES:
            run = f"{holdout}-r{share}-s{seed}"
            ring = {f"D-{i:04d}" for i in range(1, round(share * POOL) + 1)}
            for i in range(1, POOL + 1):
                drv = f"D-{i:04d}"
                labels.append([run, drv, "1" if drv in ring else "0", holdout if drv in ring else "CON"])
            for k in range(DEALS):
                deal = f"d{k}"
                chosen = rng.choice(POOL, PER_DEAL, replace=False) + 1
                drivers = [f"D-{i:04d}" for i in chosen]
                for drv in drivers:
                    actions.append([run, deal, "0.000", "DRIVER", drv, "PRESENT", "", "1", ""])
                for drv in drivers:
                    t, price = float(rng.uniform(1, 20)), float(rng.uniform(110, 200))
                    actions.append([run, deal, f"{t:.3f}", "DRIVER", drv, "BID_PLACE", f"{price:.4f}", "1", ""])
                    if drv not in ring:
                        actions.append([run, deal, f"{t + 10:.3f}", "DRIVER", drv, "BID_UPDATE", f"{price - 5:.4f}", "1", ""])
                deals.append([run, deal, "100.0000", "60.0", drivers[0], "0"])
    for name, rows in (("actions.csv", actions), ("deals_out.csv", deals), ("labels.csv", labels)):
        with open(d / name, "w", newline="", encoding="utf-8") as f:
            csv.writer(f, lineterminator="\n").writerows(rows)


def fake_results(results_dir):
    results_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(1)
    model = LogisticRegression().fit(rng.normal(size=(40, len(FEATURES))), np.array([0, 1] * 20))
    with open(results_dir / "model.pkl", "wb") as f:
        pickle.dump(model, f)
    frozen = {"features": FEATURES, "threshold": 0.5, "best_single_feature": "no_concession_share",
              "best_single_sign": 1, "best_single_threshold": 0.4,
              "model_sha256": evaluate.sha256_file(str(results_dir / "model.pkl"))}
    (results_dir / "collusion_frozen.json").write_text(json.dumps(frozen), encoding="utf-8")
    return frozen


@pytest.fixture
def dirs(tmp_path):
    raw, res = tmp_path / "raw", tmp_path / "results"
    fake_raw(raw)
    fake_results(res)
    return raw, res


def run(raw, res, *extra):
    return evaluate.main(["--holdout", "S4", "--raw-dir", str(raw), "--results-dir", str(res), *extra])


def test_without_confirm_open_nothing_is_opened(dirs):
    raw, res = dirs
    assert run(raw, res) == 2
    assert not (res / "HOLDOUT_OPENED_S4.json").exists()
    assert not (res / "T6_S4.csv").exists()


def test_opening_writes_the_record_and_both_tables_then_refuses_a_second_time(dirs):
    raw, res = dirs
    assert run(raw, res, "--confirm-open") == 0
    record = json.loads((res / "HOLDOUT_OPENED_S4.json").read_text(encoding="utf-8"))
    assert record["git_head"] == "test-mode"
    assert set(record["data_sha256"]) == {"actions.csv", "deals_out.csv", "labels.csv"}

    with open(res / "T6_S4.csv", encoding="utf-8") as f:
        t6 = list(csv.DictReader(f))
    assert list(t6[0]) == ["method", "n", "pr_auc", "ci_lo", "ci_hi", "recall_at_thr", "fpr_at_thr", "fpr_at_recall80"]
    assert [r["method"] for r in t6] == ["model", "B-price", "B-rule"]
    assert all(int(r["n"]) == len(SEEDS) * len(SHARES) * POOL for r in t6)
    for r in t6:
        assert float(r["ci_lo"]) <= float(r["pr_auc"]) + 1e-9 <= float(r["ci_hi"]) + 2e-9
    # The planted signal: colluders never concede, so B-rule (no_concession_share > 0.4) is perfect.
    rule = t6[2]
    assert float(rule["pr_auc"]) == pytest.approx(1.0)
    assert float(rule["recall_at_thr"]) == 1.0 and float(rule["fpr_at_thr"]) == 0.0

    with open(res / "F9_S4.csv", encoding="utf-8") as f:
        f9 = list(csv.DictReader(f))
    assert list(f9[0]) == ["method", "ring_share", "n", "pr_auc", "ci_lo", "ci_hi"]
    assert len(f9) == len(SHARES) * 3
    assert {float(r["ring_share"]) for r in f9} == set(SHARES)

    assert run(raw, res, "--confirm-open") == 2


def test_missing_raw_file_refuses_before_opening(tmp_path):
    raw, res = tmp_path / "raw", tmp_path / "results"
    fake_raw(raw)
    fake_results(res)
    os.remove(raw / "S4" / "labels.csv")
    assert run(raw, res, "--confirm-open") == 2
    assert not (res / "HOLDOUT_OPENED_S4.json").exists()


def test_strict_checks_hash_and_git_state(dirs):
    raw, res = dirs
    frozen_path = str(res / "collusion_frozen.json")
    clean = lambda: ""
    assert evaluate.check("S4", True, str(raw), str(res), frozen_path, True, clean)["threshold"] == 0.5
    with pytest.raises(evaluate.GuardError, match="git-tracked"):
        evaluate.check("S4", True, str(raw), str(res), frozen_path, True, lambda: " M collusion/features.py")
    with open(res / "model.pkl", "ab") as f:
        f.write(b"tampered")
    with pytest.raises(evaluate.GuardError, match="model_sha256"):
        evaluate.check("S4", True, str(raw), str(res), frozen_path, True, clean)


def test_fpr_at_recall80_takes_the_first_threshold_reaching_it():
    y = np.array([1, 1, 1, 1, 1, 0, 0, 0, 0, 0])
    score = np.array([9, 8, 7, 6, 1, 5, 4, 3, 2, 0], dtype=float)
    # Recall 0.8 needs the 4 top positives: threshold 6 flags no negative.
    assert evaluate.fpr_at_recall(y, score) == 0.0
    score[3] = 2.5  # now the 4th positive sits below three negatives
    assert evaluate.fpr_at_recall(y, score) == pytest.approx(3 / 5)


def test_test_mode_never_touches_the_real_results(dirs):
    raw, res = dirs
    real = lambda: sorted(os.listdir(evaluate.RESULTS_DIR)) if os.path.isdir(evaluate.RESULTS_DIR) else []
    before = real()
    assert run(raw, res, "--confirm-open") == 0
    assert real() == before
