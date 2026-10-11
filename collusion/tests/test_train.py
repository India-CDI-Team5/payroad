"""Card D3 checks on fake data: selection rule, LR tie rule, FPR threshold, B-rule, B-price."""

from __future__ import annotations

import numpy as np
import pytest

from collusion import train
from collusion.baselines import best_single_feature, price_outlier_scores
from collusion.features import FEATURES


def test_highest_mean_wins_when_lr_is_more_than_the_tie_behind():
    assert train.select({"LR": 0.90, "HGB-lr0.05-it200": 0.906, "HGB-lr0.1-it400": 0.95}) == "HGB-lr0.1-it400"
    assert train.select({"LR": 0.90, "HGB-lr0.05-it200": 0.9051}) == "HGB-lr0.05-it200"


def test_lr_wins_ties_within_0_005():
    assert train.select({"LR": 0.90, "HGB-lr0.05-it200": 0.905}) == "LR"
    assert train.select({"LR": 0.90, "HGB-lr0.05-it200": 0.903, "HGB-lr0.1-it200": 0.9049}) == "LR"
    assert train.select({"LR": 0.95, "HGB-lr0.05-it200": 0.90}) == "LR"


def test_exact_ties_between_hgb_keep_the_first():
    assert train.select({"LR": 0.5, "HGB-lr0.05-it200": 0.9, "HGB-lr0.05-it400": 0.9}) == "HGB-lr0.05-it200"


def test_fpr_threshold_flags_at_most_one_percent_of_negatives():
    y = np.array([0] * 200 + [1] * 10)
    score = np.concatenate([np.arange(200) / 200.0, np.full(10, 5.0)])
    t = train.fpr_threshold(score, y)
    # 200 negatives: k = 2, so the 3rd highest negative (197 / 200) is the threshold.
    assert t == pytest.approx(197 / 200)
    assert np.sum(score[y == 0] > t) == 2
    assert np.all(score[y == 1] > t)


def test_fpr_threshold_with_ties_never_exceeds_one_percent():
    y = np.array([0] * 150 + [1] * 5)
    score = np.concatenate([np.zeros(140), np.ones(10), np.ones(5)])  # 10 negatives tied at the top
    t = train.fpr_threshold(score, y)
    assert t == 1.0
    assert np.mean(score[y == 0] > t) <= 0.01


def test_folds_hold_out_one_strategy_each_in_card_order():
    strategy = np.array(["S1"] * 3 + ["S2"] * 2 + ["S3"] * 4)
    folds = train.strategy_folds(strategy)
    assert [h for h, _, _ in folds] == ["S3", "S2", "S1"]
    for held, tr, va in folds:
        assert set(strategy[va]) == {held}
        assert held not in set(strategy[tr])
        assert len(tr) + len(va) == len(strategy)


def test_five_candidates_with_the_pre_registered_settings():
    c = train.candidates()
    assert list(c) == ["LR", "HGB-lr0.05-it200", "HGB-lr0.05-it400", "HGB-lr0.1-it200", "HGB-lr0.1-it400"]
    lr = c["LR"].steps[-1][1]
    assert (lr.C, lr.class_weight, lr.max_iter) == (1.0, "balanced", 1000)
    h = c["HGB-lr0.1-it400"]
    assert (h.max_depth, h.l2_regularization, h.class_weight, h.random_state, h.learning_rate, h.max_iter) == \
        (3, 1.0, "balanced", 42, 0.1, 400)


def test_best_single_feature_finds_a_negatively_signed_feature():
    rng = np.random.default_rng(0)
    y = np.array([0, 1] * 60)
    X = rng.normal(size=(len(y), len(FEATURES)))
    j = FEATURES.index("withdraw_rate")
    X[:, j] = -3.0 * y + rng.normal(scale=0.1, size=len(y))  # low value = colluder
    strategy = np.array(["S1", "S2", "S3"] * 40)
    folds = [(tr, va) for _, tr, va in train.strategy_folds(strategy)]
    assert best_single_feature(X, y, folds) == ("withdraw_rate", -1)


def test_cross_validation_runs_on_fake_data_and_pools_every_row():
    rng = np.random.default_rng(1)
    n = 180
    y = rng.integers(0, 2, n)
    X = rng.normal(size=(n, len(FEATURES))) + y[:, None] * 0.5
    strategy = np.repeat(["S1", "S2", "S3"], n // 3)
    folds, results = train.cross_validate(X, y, strategy)
    assert len(results) == 5
    for per, oof in results.values():
        assert set(per) == {"S1", "S2", "S3"}
        assert np.isfinite(oof).all()


def test_price_outlier_z_scores_within_a_run(tmp_path):
    deals = tmp_path / "deals_out.csv"
    deals.write_text("run_id,deal_id,base_price,winner_strategy\nR,d1,100,S1\nR,d2,200,S1\n", encoding="utf-8")
    actions = tmp_path / "actions.csv"
    actions.write_text("\n".join([
        "run_id,deal_id,t_sec,actor_type,driver_id,action,price,accepted,reject_code",
        "R,d1,0,DRIVER,A,PRESENT,,1,", "R,d1,0,DRIVER,B,PRESENT,,1,", "R,d1,0,DRIVER,C,PRESENT,,1,",
        "R,d2,0,DRIVER,A,PRESENT,,1,",
        "R,d1,1,DRIVER,A,BID_PLACE,150,1,", "R,d1,9,DRIVER,A,BID_UPDATE,120,1,",   # last 1.2
        "R,d2,2,DRIVER,A,BID_PLACE,320,1,",                                         # 1.6 -> mean 1.4
        "R,d1,3,DRIVER,B,BID_PLACE,100,1,", "R,d1,4,DRIVER,B,BID_UPDATE,90,0,",    # rejected: last 1.0
        "R,d1,5,RIDER,R-SIM,OFFER_POST,80,1,",
    ]) + "\n", encoding="utf-8")
    z = price_outlier_scores(str(deals), str(actions))
    # Bidders A (1.4) and B (1.0): mean 1.2, std 0.2.
    assert z[("R", "A")] == pytest.approx(1.0)
    assert z[("R", "B")] == pytest.approx(-1.0)
    assert z[("R", "C")] == 0.0
