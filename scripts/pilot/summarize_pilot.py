"""User pilot summary (card E3, ml-design v5 §8.2): does a human rider pick the cheapest bid?

Run from the repository root after saving the export (docs/pilot-protocol.md step 5):
  python scripts/pilot/summarize_pilot.py

Input is the CSV from GET /api/admin/deal-history.csv?tag=pilot (DealHistoryExportController), one row
per closed deal. Output is one row, results/pilot/pilot_summary.csv.

Definitions fixed here:
  n_deals                  every row (MATCHED, EXPIRED and CANCELLED)
  n_matched                endStatus = MATCHED
  rider_picked_bid_share   matchPath = RIDER_PICKED_BID among MATCHED
  driver_took_offer_share  matchPath = DRIVER_TOOK_OFFER among MATCHED
  n_rider_picked           MATCHED deals the rider closed by picking a bid; the denominator of the next four
  rank1_share              chosenRank = 1 (the cheapest bid at match time) among n_rider_picked
  n_rank_gt1               chosenRank > 1 among n_rider_picked
  mean_extra_paid_ratio    mean of (finalPrice - lowestBidPrice) / basePrice over n_rider_picked
  mean_eta_saved_min       mean of lowestBidPickupEtaMin - winningPickupEtaMin over n_rider_picked
The last four use rider-picked deals only: a driver taking the rider's offer has chosenRank 0 and its price
is the rider's own offer, so it says nothing about which bid the rider chose (same as E5 in
scripts/sim/summarize.py). A statistic with no deal to average is left blank.
"""
import argparse
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
INPUT = os.path.join(ROOT, "results", "pilot", "pilot_deals.csv")
OUTPUT = os.path.join(ROOT, "results", "pilot", "pilot_summary.csv")

FIELDS = ("n_deals", "n_matched", "rider_picked_bid_share", "driver_took_offer_share", "n_rider_picked",
          "rank1_share", "n_rank_gt1", "mean_extra_paid_ratio", "mean_eta_saved_min")


def _num(v):
    return float(v) if v not in ("", None) else None


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _share(k, n):
    return k / n if n else None


def summarize(rows):
    matched = [r for r in rows if r["endStatus"] == "MATCHED"]
    picked = [r for r in matched if r["matchPath"] == "RIDER_PICKED_BID"]
    took = [r for r in matched if r["matchPath"] == "DRIVER_TOOK_OFFER"]
    ranks = [int(r["chosenRank"]) for r in picked]
    extra = [(_num(r["finalPrice"]) - _num(r["lowestBidPrice"])) / _num(r["basePrice"])
             for r in picked if _num(r["lowestBidPrice"]) is not None]
    eta = [_num(r["lowestBidPickupEtaMin"]) - _num(r["winningPickupEtaMin"])
           for r in picked if _num(r["lowestBidPickupEtaMin"]) is not None and _num(r["winningPickupEtaMin"]) is not None]
    return {
        "n_deals": len(rows),
        "n_matched": len(matched),
        "rider_picked_bid_share": _share(len(picked), len(matched)),
        "driver_took_offer_share": _share(len(took), len(matched)),
        "n_rider_picked": len(picked),
        "rank1_share": _share(sum(1 for k in ranks if k == 1), len(picked)),
        "n_rank_gt1": sum(1 for k in ranks if k > 1),
        "mean_extra_paid_ratio": _mean(extra),
        "mean_eta_saved_min": _mean(eta),
    }


def _fmt(v):
    if v is None:
        return ""
    return f"{v:.4f}" if isinstance(v, float) else str(v)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--input", default=INPUT)
    p.add_argument("--output", default=OUTPUT)
    a = p.parse_args(argv)
    with open(a.input, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    s = summarize(rows)
    os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
    with open(a.output, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        w.writerow([_fmt(s[k]) for k in FIELDS])
    print(f"{a.output}: " + ", ".join(f"{k}={_fmt(s[k])}" for k in FIELDS))
    if s["n_matched"] < 30:
        print(f"note: n_matched = {s['n_matched']} < 30 (card E3). Report it as is and state n in the paper.")
    return s


if __name__ == "__main__":
    main()
