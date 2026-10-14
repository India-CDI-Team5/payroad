"""Run from the repository root: python -m pytest scripts/sim"""
import csv
import importlib.util
from pathlib import Path

import numpy as np

_spec = importlib.util.spec_from_file_location("posthoc_offer", Path(__file__).with_name("posthoc_offer.py"))
po = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(po)


def write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def fake_level(d, rho, lo, monotone, markups):
    write_csv(d / "E1_trend.csv", ["config", "spearman_n_markup", "diff_n1_minus_n10", "ci_lo", "ci_hi",
                                   "monotone_decrease"], [["C1", rho, "0.1", lo, "0.2", monotone]])
    write_csv(d / "E1_summary.csv", ["config", "n", "runs", "markup_median", "ci_lo", "ci_hi", "match_rate",
                                     "mr_ci_lo", "mr_ci_hi"],
              [["C1", n, 30, markups[n], "", "", 0.9 - 0.01 * n, "", ""] for n in range(1, 11)])


def test_offer_table_joins_trend_and_summary(tmp_path):
    fake_level(tmp_path / "a", "-0.9", "0.05", "1", {n: 1 - 0.01 * n for n in range(1, 11)})
    fake_level(tmp_path / "b", "", "0.0", "0", {n: 1.0 for n in range(1, 11)})
    rows = po.offer_table((("0.80", tmp_path / "a"), ("1.00", tmp_path / "b")))
    assert len(rows) == 2
    assert dict(zip(po.OFFER_COLUMNS, rows[0])) == {
        "offer_base": "0.80", "config": "C1", "spearman_n_markup": "-0.9", "diff_n1_minus_n10": "0.1",
        "ci_lo": "0.05", "ci_hi": "0.2", "monotone_decrease": "1", "markup_n1": "0.99", "markup_n10": "0.9",
        "match_n1": "0.89", "match_n5": "0.85", "match_n10": "0.8"}
    assert rows[1][2] == "" and rows[1][6] == "0"                 # constant markup: no ρ, does not pass


def test_rank_premium_counts_only_picked_deals(tmp_path):
    header = ["config", "param_tau", "status", "chosen_rank", "final_price", "lowest_bid_price", "base_price",
              "lowest_bid_pickup_eta", "winner_pickup_eta"]
    rows = [
        ["C1", "0.05", "MATCHED", "1", "100", "100", "100", "8", "8"],
        ["C1", "0.05", "MATCHED", "2", "110", "100", "100", "9", "5"],
        ["C1", "0.05", "MATCHED", "3", "120", "100", "200", "10", "4"],
        ["C1", "0.05", "MATCHED", "0", "90", "", "100", "", ""],        # driver took the offer: no rank
        ["C1", "0.05", "EXPIRED", "", "", "", "100", "", ""],
        ["C1", "0", "MATCHED", "1", "100", "100", "100", "3", "3"],
    ]
    path = tmp_path / "deals_out.csv"
    write_csv(path, header, rows)
    out = {(r[0], r[1]): r for r in po.rank_table(path)}
    c = out[("C1", "0.05")]
    assert c[2] == 3
    assert np.isclose(c[3], 2 / 3)
    assert np.isclose(c[4], (0.10 + 0.10) / 2)                       # (110-100)/100, (120-100)/200
    assert np.isclose(c[5], (4 + 6) / 2)
    z = out[("C1", "0")]
    assert z[2] == 1 and z[3] == 0.0 and np.isnan(z[4]) and np.isnan(z[5])
