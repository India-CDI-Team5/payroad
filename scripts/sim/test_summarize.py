"""Run from the repository root: python -m pytest scripts/sim"""
import csv
import importlib.util
from pathlib import Path

import numpy as np
import pytest

_spec = importlib.util.spec_from_file_location("summarize", Path(__file__).with_name("summarize.py"))
sm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sm)

COLUMNS = list(sm.TEXT + sm.NUMBER)


def deal(run_id, config="C1", seed=1, n=5, status="MATCHED", end_reason="", match_path="RIDER_PICKED_BID", mode="",
         beta_mode="", markup=1.1, markup_dry=None, chosen_rank=1, eta=3.0, rounds=4, duration=60.0, ttl=30,
         round_limit=20, tau=""):
    matched = status == "MATCHED"
    return {"run_id": run_id, "config": config, "status": status, "end_reason": end_reason,
            "match_path": match_path if matched else "", "mode": mode, "beta_mode": beta_mode, "seed": seed,
            "n_drivers": n, "markup": markup if matched else "", "markup_dry": (markup_dry or markup) if matched else "",
            "chosen_rank": chosen_rank if matched else "", "winner_pickup_eta": eta if matched else "",
            "round_count": rounds, "duration_sec": duration, "param_offer_ttl": ttl, "param_round_limit": round_limit,
            "param_tau": tau}


def write_raw(tmp_path, scenario, rows):
    d = tmp_path / "raw" / scenario
    d.mkdir(parents=True)
    with open(d / "deals_out.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return tmp_path / "raw"


def read_out(tmp_path, name):
    with open(tmp_path / "out" / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_bootstrap_is_seeded_and_brackets_the_mean():
    v = [1.0, 2.0, 3.0, 4.0, np.nan]
    m, lo, hi = sm.bootstrap(v)
    assert m == 2.5 and lo <= m <= hi
    assert sm.bootstrap(v) == (m, lo, hi)
    assert sm.bootstrap([0.7] * 5) == pytest.approx((0.7, 0.7, 0.7))
    assert all(np.isnan(x) for x in sm.bootstrap([np.nan]))


def test_spearman_with_ties():
    assert sm.spearman([1, 2, 3, 4], [9, 7, 5, 1]) == pytest.approx(-1.0)
    assert sm.spearman([1, 2, 3, 4], [1, 1, 2, 2]) == pytest.approx(0.894427, abs=1e-6)
    assert np.isnan(sm.spearman([1, 2], [3, 4]))


def test_e1_summary_and_trend(tmp_path):
    rows = []
    for config, slope in (("C1", -0.02), ("C2", 0.01)):
        for seed in (1, 2, 3):
            for n in range(1, 11):
                rid = f"e1-{config}-n{n}-s{seed}"
                for i in range(4):
                    rows.append(deal(rid, config, seed, n, markup=1.3 + slope * n + 0.001 * seed + 0.0001 * i))
                rows.append(deal(rid, config, seed, n, status="EXPIRED", end_reason="ROUND_LIMIT"))
    raw = write_raw(tmp_path, "e1", rows)
    counts = sm.summarize("e1", raw, tmp_path / "out")
    assert counts == {"E1_summary.csv": 20, "E1_trend.csv": 2}

    s = read_out(tmp_path, "E1_summary.csv")
    first = s[0]
    assert (first["config"], first["n"], first["runs"]) == ("C1", "1", "3")
    assert float(first["match_rate"]) == pytest.approx(0.8)
    assert float(first["markup_median"]) == pytest.approx(1.28 + 0.002 + 0.00015)   # median of 4, mean over seeds
    t = {r["config"]: r for r in read_out(tmp_path, "E1_trend.csv")}
    assert float(t["C1"]["spearman_n_markup"]) == pytest.approx(-1.0)
    assert float(t["C1"]["diff_n1_minus_n10"]) == pytest.approx(0.18)
    assert t["C1"]["monotone_decrease"] == "1"
    assert float(t["C2"]["spearman_n_markup"]) == pytest.approx(1.0)
    assert t["C2"]["monotone_decrease"] == "0"


def test_run_without_a_match_is_left_out_of_the_markup(tmp_path):
    rows = [deal("e1-C1-n1-s1", seed=1, n=1, markup=1.2), deal("e1-C1-n1-s2", seed=2, n=1, status="EXPIRED",
                                                                end_reason="TTL")]
    raw = write_raw(tmp_path, "e1", rows)
    sm.summarize("e1", raw, tmp_path / "out")
    r = read_out(tmp_path, "E1_summary.csv")[0]
    assert float(r["markup_median"]) == pytest.approx(1.2)
    assert float(r["match_rate"]) == pytest.approx(0.5)


def test_e2_shares(tmp_path):
    rows = [deal("e2-C1-s1", rounds=2, duration=10), deal("e2-C1-s1", rounds=2, duration=20),
            deal("e2-C1-s1", status="EXPIRED", end_reason="TTL", rounds=5, duration=180),
            deal("e2-C1-s1", status="EXPIRED", end_reason="ROUND_LIMIT", rounds=20, duration=90)]
    raw = write_raw(tmp_path, "e2", rows)
    counts = sm.summarize("e2", raw, tmp_path / "out")
    assert counts["E2_rounds.csv"] == 21                       # round_count 0..20
    rounds = read_out(tmp_path, "E2_rounds.csv")
    assert sum(float(r["share"]) for r in rounds) == pytest.approx(1.0)
    assert float(rounds[2]["share"]) == pytest.approx(0.5)
    end = read_out(tmp_path, "E2_end.csv")[0]
    assert [float(end[k]) for k in ("matched", "ttl", "round_limit")] == pytest.approx([0.5, 0.25, 0.25])
    dur = read_out(tmp_path, "E2_duration.csv")[0]
    assert float(dur["p50"]) == pytest.approx(55.0)


def test_e3_keeps_the_two_variants_of_one_run_apart(tmp_path):
    rows = [deal("e3-C1-s1", mode="bargain", duration=40, eta=5),
            deal("e3-C1-s1", mode="bargain", status="EXPIRED", end_reason="TTL"),
            deal("e3-C1-s1", mode="fixed", duration=8, eta=2),
            deal("e3-C1-s1", mode="fixed", duration=12, eta=4)]
    raw = write_raw(tmp_path, "e3", rows)
    sm.summarize("e3", raw, tmp_path / "out")
    out = {r["mode"]: r for r in read_out(tmp_path, "E3_fixed.csv")}
    assert float(out["bargain"]["match_rate"]) == pytest.approx(0.5)
    assert float(out["bargain"]["time_to_match_median"]) == pytest.approx(40)
    assert float(out["fixed"]["match_rate"]) == pytest.approx(1.0)
    assert float(out["fixed"]["winner_eta_mean"]) == pytest.approx(3.0)


def test_e4_one_row_per_cell(tmp_path):
    rows = [deal(f"e4-C1-ttl{t}-rl{r}-s1", ttl=t, round_limit=r) for t in (10, 20, 30, 60) for r in (5, 10, 20, 40)]
    raw = write_raw(tmp_path, "e4", rows)
    assert sm.summarize("e4", raw, tmp_path / "out") == {"E4_heatmap.csv": 16}
    first = read_out(tmp_path, "E4_heatmap.csv")[0]
    assert (first["offer_ttl"], first["round_limit"]) == ("10", "5")


def test_e5_ranks_only_count_deals_the_rider_picked(tmp_path):
    rows = [deal("e5-C1-tau0.00-s1", tau=0.0, chosen_rank=1), deal("e5-C1-tau0.00-s1", tau=0.0, chosen_rank=2),
            deal("e5-C1-tau0.00-s1", tau=0.0, chosen_rank=0, match_path="DRIVER_TOOK_OFFER"),
            deal("e5-C1-tau0.00-s1", tau=0.0, chosen_rank=4)]
    raw = write_raw(tmp_path, "e5", rows)
    sm.summarize("e5", raw, tmp_path / "out")
    r = read_out(tmp_path, "E5_tau.csv")[0]
    assert [float(r[k]) for k in ("rank1_share", "rank2_share", "rank3plus_share")] == pytest.approx([1 / 3] * 3)


def test_e6_beta_modes(tmp_path):
    rows = [deal("e6-C1-s1", beta_mode="on", markup=1.2, markup_dry=1.4),
            deal("e6-C1-s1", beta_mode="off", markup=1.1, markup_dry=1.1)]
    raw = write_raw(tmp_path, "e6", rows)
    sm.summarize("e6", raw, tmp_path / "out")
    out = {r["beta_mode"]: r for r in read_out(tmp_path, "E6_weather.csv")}
    assert float(out["on"]["markup_dry_median"]) == pytest.approx(1.4)
    assert float(out["off"]["markup_dry_median"]) == pytest.approx(1.1)
