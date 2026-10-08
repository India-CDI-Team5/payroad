import datetime
import hashlib
import json
import os

import pytest

from training import freeze

KEYS = ["frozen_utc", "gp_interpolator_sha256", "gp_rt_sha256", "pricing_constants_sha256", "rhos", "k_abs",
        "methods", "subsets", "draws", "draw_seed_rule", "pairs", "pair_rhos", "test", "correction", "alpha",
        "bootstrap", "uncertainty_bins", "saving_rho_grid_step", "beta_compare_rho"]


def test_sha256_is_the_hash_of_the_raw_bytes(tmp_path):
    p = tmp_path / "x.json"
    p.write_bytes(b'{"a": 1}\r\n')
    assert freeze.sha256_file(p) == hashlib.sha256(b'{"a": 1}\r\n').hexdigest()


def test_record_has_the_fixed_keys_and_only_the_time_changes():
    a = freeze.frozen(datetime.datetime(2026, 10, 8, 0, 0, tzinfo=datetime.timezone.utc))
    b = freeze.frozen(datetime.datetime(2026, 10, 9, 12, 0, tzinfo=datetime.timezone.utc))
    assert list(a) == KEYS
    assert a["frozen_utc"] == "2026-10-08T00:00:00Z"
    assert {k: v for k, v in a.items() if k != "frozen_utc"} == {k: v for k, v in b.items() if k != "frozen_utc"}


def test_main_writes_the_same_hashes_twice(tmp_path):
    out = tmp_path / "frozen.json"
    freeze.main(["--out", str(out)])
    first = json.loads(out.read_text(encoding="utf-8"))
    freeze.main(["--out", str(out)])
    second = json.loads(out.read_text(encoding="utf-8"))
    first.pop("frozen_utc"), second.pop("frozen_utc")
    assert first == second


def test_committed_freeze_matches_the_files_it_hashes():
    if not os.path.exists(freeze.OUT_PATH):
        pytest.skip("configs/model_a_frozen.json not written yet")
    with open(freeze.OUT_PATH, encoding="utf-8") as f:
        record = json.load(f)
    assert list(record) == KEYS
    for key, path in freeze.HASHED.items():
        assert record[key] == freeze.sha256_file(path), f"{path} changed after the freeze"
    assert {k: record[k] for k in freeze.PLAN} == freeze.PLAN


def test_pricing_constants_have_the_fixed_keys():
    with open(freeze.HASHED["pricing_constants_sha256"], encoding="utf-8") as f:
        c = json.load(f)
    assert list(c) == ["version", "source", "baseFee", "perKm", "betaCoef", "betaCap", "uncertaintyWeight",
                       "surchargeThreshold", "surgeMin", "surgeMax", "betaSensitivity", "servingBudgetRatio",
                       "servingDraws"]
    assert c["baseFee"] >= 0 and c["perKm"] > 0
