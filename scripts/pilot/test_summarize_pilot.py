"""Run from the repository root: python -m pytest scripts/pilot"""
import csv
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("summarize_pilot", Path(__file__).with_name("summarize_pilot.py"))
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)

# Header of GET /api/admin/deal-history.csv (DealHistoryExportController.COLUMNS).
HEADER = ["id", "dealId", "experimentTag", "randomSeed", "userId", "driverId", "createdAt", "matchedAt",
          "endStatus", "endReason", "matchPath", "chosenRank", "basePrice", "finalPrice", "markupRatio",
          "lowestBidPrice", "pickupDistanceKm", "winningPickupDistanceKm", "winningPickupEtaMin",
          "lowestBidPickupDistanceKm", "lowestBidPickupEtaMin", "demandInRadius", "supplyInRadius", "roundCount",
          "bidderCount", "withdrawCount", "negotiationDurationMs"]


def deal(status="MATCHED", path="RIDER_PICKED_BID", rank=1, base=100.0, final=100.0, lowest=100.0,
         win_eta=5.0, low_eta=5.0, reason=""):
    matched = status == "MATCHED"
    row = dict.fromkeys(HEADER, "")
    row.update({"experimentTag": "pilot", "endStatus": status, "endReason": reason, "basePrice": base,
                "finalPrice": final if matched else 0.0})
    if matched:
        row.update({"matchPath": path, "chosenRank": rank, "lowestBidPrice": lowest,
                    "winningPickupEtaMin": win_eta, "lowestBidPickupEtaMin": low_eta})
    return row


def run(tmp_path, rows):
    src, out = tmp_path / "pilot_deals.csv", tmp_path / "out" / "pilot_summary.csv"
    with open(src, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)
    sp.main(["--input", str(src), "--output", str(out)])
    with open(out, newline="", encoding="utf-8") as f:
        got = list(csv.DictReader(f))
    assert len(got) == 1 and list(got[0]) == list(sp.FIELDS)
    return got[0]


def test_counts_shares_and_means(tmp_path):
    rows = [
        deal(rank=1, final=100, lowest=100, win_eta=4, low_eta=4),        # cheapest
        deal(rank=2, final=110, lowest=100, win_eta=3, low_eta=9),        # paid +0.10 to save 6 min
        deal(rank=3, final=120, lowest=100, win_eta=2, low_eta=10),       # paid +0.20 to save 8 min
        deal(path="DRIVER_TOOK_OFFER", rank=0, final=80, lowest=95),      # not a bid choice: left out
        deal(status="EXPIRED", reason="TTL"),
        deal(status="CANCELLED", reason="CANCELLED_BY_RIDER"),
    ]
    s = run(tmp_path, rows)
    assert s["n_deals"] == "6"
    assert s["n_matched"] == "4"
    assert float(s["rider_picked_bid_share"]) == pytest.approx(0.75)
    assert float(s["driver_took_offer_share"]) == pytest.approx(0.25)
    assert s["n_rider_picked"] == "3"
    assert float(s["rank1_share"]) == pytest.approx(1 / 3, abs=1e-4)
    assert s["n_rank_gt1"] == "2"
    assert float(s["mean_extra_paid_ratio"]) == pytest.approx(0.10)
    assert float(s["mean_eta_saved_min"]) == pytest.approx(14 / 3, abs=1e-4)


def test_no_match_leaves_statistics_blank(tmp_path):
    s = run(tmp_path, [deal(status="EXPIRED", reason="TTL")])
    assert s["n_deals"] == "1" and s["n_matched"] == "0" and s["n_rank_gt1"] == "0"
    for k in ("rider_picked_bid_share", "driver_took_offer_share", "rank1_share", "mean_extra_paid_ratio",
              "mean_eta_saved_min"):
        assert s[k] == ""
