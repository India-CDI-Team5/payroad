"""Card D2 checks: hand-computed feature values, no label input, no label words in the code."""

from __future__ import annotations

import inspect
import os

import numpy as np
import pytest

from collusion import features
from collusion.dataset import build_dataset, parse_run_id
from collusion.features import FEATURES, build_features

ACTION_HEADER = "run_id,deal_id,t_sec,actor_type,driver_id,action,price,accepted,reject_code"
RUN = "S1-r0.5-s1"

# 20 rows: drivers A and B appear together in 5 deals (10 PRESENT rows) and take 10 actions.
ACTIONS = [
    *(f"{RUN},d{i},0.000,DRIVER,{d},PRESENT,,1," for i in range(1, 6) for d in ("A", "B")),
    f"{RUN},d1,2.000,DRIVER,A,BID_PLACE,100.0000,1,",
    f"{RUN},d1,4.000,DRIVER,B,BID_PLACE,100.2000,1,",
    f"{RUN},d1,20.000,DRIVER,A,BID_UPDATE,99.0000,1,",   # A goes under B's live bid
    f"{RUN},d2,1.000,DRIVER,A,BID_PLACE,120.0000,1,",
    f"{RUN},d2,10.000,DRIVER,B,BID_PLACE,110.0000,1,",   # B goes under A's live bid
    f"{RUN},d3,5.000,DRIVER,A,BID_PLACE,90.0000,1,",
    f"{RUN},d3,8.000,DRIVER,A,WITHDRAW,,1,",             # inside the last 30 s of a 30 s deal
    f"{RUN},d4,3.000,DRIVER,B,BID_PLACE,95.0000,1,",
    f"{RUN},d4,4.000,DRIVER,A,BID_PLACE,95.0000,1,",
    f"{RUN},d5,6.000,DRIVER,B,BID_PLACE,80.0000,1,",
]
# winners: d1 A, d2 B, d3 none, d4 A, d5 none; base_price 100 everywhere
DEALS = {"d1": ("50.0", "A"), "d2": ("40.0", "B"), "d3": ("30.0", ""), "d4": ("60.0", "A"), "d5": ("180.0", "")}


def write(tmp_path, actions, deal_header, deal_row) -> tuple[str, str]:
    a = tmp_path / "actions.csv"
    a.write_text("\n".join([ACTION_HEADER, *actions]) + "\n", encoding="utf-8")
    d = tmp_path / "deals_out.csv"
    d.write_text("\n".join([deal_header] + [deal_row(k, v) for k, v in DEALS.items()]) + "\n", encoding="utf-8")
    return str(a), str(d)


def five_columns(tmp_path, actions=ACTIONS) -> tuple[str, str]:
    return write(tmp_path, actions, "run_id,deal_id,base_price,duration_sec,winner_id",
                 lambda k, v: f"{RUN},{k},100.0000,{v[0]},{v[1]}")


def value(keys, X, driver, name) -> float:
    return X[keys.index((RUN, driver)), FEATURES.index(name)]


def test_hand_computed_values(tmp_path):
    assert len(ACTIONS) == 20
    keys, X = build_features(*five_columns(tmp_path))
    assert keys == [(RUN, "A"), (RUN, "B")]
    assert X.shape == (2, len(FEATURES))

    # withdraw_rate: A withdrew once over 5 bid actions (4 PLACE + 1 UPDATE); B never.
    assert value(keys, X, "A", "withdraw_rate") == pytest.approx(1 / 5)
    assert value(keys, X, "B", "withdraw_rate") == 0
    assert value(keys, X, "A", "late_withdraw_rate") == pytest.approx(1 / 5)
    assert value(keys, X, "A", "update_rate") == pytest.approx(1 / 4)
    assert value(keys, X, "A", "participation_rate") == pytest.approx(4 / 5)
    assert value(keys, X, "A", "win_rate") == pytest.approx(2 / 4)
    assert value(keys, X, "A", "relative_step_mean") == pytest.approx(1 / 100)
    assert value(keys, X, "A", "concession_interval_mean") == pytest.approx(18)
    assert value(keys, X, "B", "concession_interval_mean") == 180
    assert value(keys, X, "A", "entry_after_first_other_mean") == pytest.approx(np.mean([2 - 4, 1 - 10, 4 - 3]))

    for d in ("A", "B"):
        # Both bid in d1, d2, d4. First bids 2 s, 9 s, 1 s apart: 2 of 3 within 3 s.
        assert value(keys, X, d, "sync_entry_max") == pytest.approx(2 / 3)
        assert value(keys, X, d, "sync_entry_mean") == pytest.approx(2 / 3)
        # Last bids: 99 vs 100.2 (1.2), 120 vs 110 (10), 95 vs 95 (0); under 0.005 × 100 only in d4.
        assert value(keys, X, d, "tie_rate_max") == pytest.approx(1 / 3)
        assert value(keys, X, d, "tie_rate_mean") == pytest.approx(1 / 3)
        # Wins A 2, B 1: 1 − |2 − 1| / 3.
        assert value(keys, X, d, "alternation_max") == pytest.approx(2 / 3)
        assert value(keys, X, d, "alternation_mean") == pytest.approx(2 / 3)
        # Undercut in d1 (A) and d2 (B), not in d4.
        assert value(keys, X, d, "no_undercut_max") == pytest.approx(1 / 3)
        assert value(keys, X, d, "cowithdraw_max") == 0
        assert value(keys, X, d, "n_partners") == 1


def test_pairs_below_five_deals_together_are_ignored(tmp_path):
    actions = [r for r in ACTIONS if ",d5," not in r]
    keys, X = build_features(*five_columns(tmp_path, actions))
    pair_columns = [i for i, n in enumerate(FEATURES) if n.endswith(("_max", "_mean")) and n not in
                    ("entry_delay_mean", "concession_interval_mean", "relative_step_mean",
                     "entry_after_first_other_mean")]
    assert len(pair_columns) == 10
    assert np.all(X[:, pair_columns] == 0)
    assert np.all(X[:, FEATURES.index("n_partners")] == 0)


def test_rider_rows_and_leaking_deal_columns_change_nothing(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    base = build_features(*five_columns(tmp_path / "a"))[1]
    rider = [*ACTIONS, f"{RUN},d1,30.000,RIDER,R-SIM,OFFER_POST,70.0000,1,",
             f"{RUN},d1,31.000,RIDER,R-SIM,ACCEPT_BID,99.0000,1,"]
    full_header = "run_id,deal_id,base_price,duration_sec,winner_id,winner_strategy,winner_is_colluder"
    leak = write(tmp_path / "b", rider, full_header, lambda k, v: f"{RUN},{k},100.0000,{v[0]},{v[1]},S1,1")
    assert np.array_equal(build_features(*leak)[1], base)


def test_no_label_input_and_no_label_words():
    assert list(inspect.signature(build_features).parameters) == ["actions_csv", "deals_csv"]
    source = inspect.getsource(features)
    assert "is_colluder" not in source
    assert "strategy" not in source
    assert set(features.DEAL_COLUMNS) == {"run_id", "deal_id", "base_price", "duration_sec", "winner_id"}


def test_dataset_joins_labels_by_run_and_driver(tmp_path):
    (tmp_path / "S1").mkdir()
    write(tmp_path / "S1", ACTIONS, "run_id,deal_id,base_price,duration_sec,winner_id",
          lambda k, v: f"{RUN},{k},100.0000,{v[0]},{v[1]}")
    (tmp_path / "S1" / "labels.csv").write_text(
        f"run_id,driver_id,is_colluder,strategy\n{RUN},A,1,S1\n{RUN},B,0,CON\n", encoding="utf-8")
    keys, X, y, strategy, share = build_dataset([str(tmp_path / "S1")])
    assert keys.tolist() == [[RUN, "A"], [RUN, "B"]]
    assert y.tolist() == [1, 0]
    assert strategy.tolist() == ["S1", "S1"]
    assert share.tolist() == [0.5, 0.5]
    assert X.shape == (2, len(FEATURES))
    assert parse_run_id("S3-r0.1-s10") == ("S3", 0.1)


@pytest.mark.skipif(not os.path.exists("results/sim/raw/collusion/S1/actions.csv"), reason="raw data not generated")
def test_real_s1_head_has_no_missing_deals():
    # The first 200 action rows and their deals must load without errors (card D2 reading list).
    import itertools
    import tempfile
    with open("results/sim/raw/collusion/S1/actions.csv", encoding="utf-8") as f:
        head = list(itertools.islice(f, 201))
    with tempfile.TemporaryDirectory() as d:
        a = os.path.join(d, "actions.csv")
        with open(a, "w", encoding="utf-8") as f:
            f.writelines(head)
        keys, X = build_features(a, "results/sim/raw/collusion/S1/deals_out.csv")
    assert len(keys) > 0 and np.isfinite(X).all()
