"""Post-hoc mechanism tables (paper-revision-v1 X4): the rider's first offer level and what non-lowest picks buy.

Run from the repository root after the two runs with --offer-base and summarize.py on each:
  python scripts/sim/posthoc_offer.py

E1_offer_base.csv  offer_base 0.80 is the frozen E1 (results/sim/E1_trend.csv, E1_summary.csv, read only);
                   0.90 and 1.00 come from results/posthoc/sim/ob090 and ob100 (summarize.py e1 outputs).
                   monotone_decrease is summarize.py's pre-registered rule (ρ < 0 and ci_lo > 0); an undefined ρ
                   (constant markup) does not pass.
E5_rank_premium.csv  from the frozen raw E5 run (results/sim/raw/e5/deals_out.csv): MATCHED deals the rider closed
                   by picking a bid (chosen_rank >= 1). share_nonlowest = chosen_rank >= 2; for those deals the mean
                   of (final_price - lowest_bid_price) / base_price and of lowest_bid_pickup_eta - winner_pickup_eta
                   (minutes). Bot behaviour, not a statement about real riders.
"""
import csv
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
FROZEN = os.path.join(ROOT, "results", "sim")
POSTHOC = os.path.join(ROOT, "results", "posthoc", "sim")
RAW_E5 = os.path.join(ROOT, "results", "sim", "raw", "e5", "deals_out.csv")
LEVELS = (("0.80", FROZEN), ("0.90", os.path.join(POSTHOC, "ob090")), ("1.00", os.path.join(POSTHOC, "ob100")))

OFFER_COLUMNS = ["offer_base", "config", "spearman_n_markup", "diff_n1_minus_n10", "ci_lo", "ci_hi",
                 "monotone_decrease", "markup_n1", "markup_n10", "match_n1", "match_n5", "match_n10"]
RANK_COLUMNS = ["config", "tau", "n_picked", "share_nonlowest", "extra_price_ratio_mean", "eta_saved_min_mean"]


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def offer_table(levels=LEVELS):
    out = []
    for level, d in levels:
        trend = read(os.path.join(d, "E1_trend.csv"))
        summary = {(r["config"], int(r["n"])): r for r in read(os.path.join(d, "E1_summary.csv"))}
        for t in trend:
            c = t["config"]
            out.append([level, c, t["spearman_n_markup"], t["diff_n1_minus_n10"], t["ci_lo"], t["ci_hi"],
                        t["monotone_decrease"], summary[(c, 1)]["markup_median"], summary[(c, 10)]["markup_median"],
                        summary[(c, 1)]["match_rate"], summary[(c, 5)]["match_rate"], summary[(c, 10)]["match_rate"]])
    return out


def num(v):
    return float(v) if v != "" else np.nan


def rank_table(raw_path=RAW_E5):
    groups = {}
    with open(raw_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["status"] != "MATCHED" or num(r["chosen_rank"]) < 1:
                continue
            groups.setdefault((r["config"], r["param_tau"]), []).append(r)
    out = []
    for (config, tau), rs in groups.items():
        rank = np.array([num(r["chosen_rank"]) for r in rs])
        non = [r for r, k in zip(rs, rank) if k >= 2]
        extra = [(num(r["final_price"]) - num(r["lowest_bid_price"])) / num(r["base_price"]) for r in non]
        saved = [num(r["lowest_bid_pickup_eta"]) - num(r["winner_pickup_eta"]) for r in non]
        out.append([config, tau, len(rs), float((rank >= 2).mean()),
                    float(np.nanmean(extra)) if non else np.nan, float(np.nanmean(saved)) if non else np.nan])
    return out


def cell(v):
    if isinstance(v, (float, np.floating)):
        return "" if np.isnan(v) else f"{float(v):.6f}"
    return v


def write(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows([[cell(v) for v in r] for r in rows])


def main():
    offer = offer_table()
    write(os.path.join(POSTHOC, "E1_offer_base.csv"), OFFER_COLUMNS, offer)
    rank = rank_table()
    write(os.path.join(POSTHOC, "E5_rank_premium.csv"), RANK_COLUMNS, rank)
    print(f"E1_offer_base.csv {len(offer)} rows, E5_rank_premium.csv {len(rank)} rows")


if __name__ == "__main__":
    main()
