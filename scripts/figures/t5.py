"""T5: user pilot, a preliminary observation (results/pilot/pilot_summary.csv)."""
import os

import style

# column -> (label, is a count)
METRICS = [
    ("n_deals", "Deals opened", True),
    ("n_matched", "Deals matched", True),
    ("rank1_share", "Share choosing the lowest bid", False),
    ("n_rank_gt1", "Matches not on the lowest bid", True),
    ("mean_extra_paid_ratio", "Mean extra paid / base price", False),
    ("mean_eta_saved_min", "Mean pickup ETA saved (min)", False),
    ("rider_picked_bid_share", "Share closed by rider picking a bid", False),
    ("driver_took_offer_share", "Share closed by driver taking the offer", False),
]


def make(results_dir, out_dir):
    rows = style.read_csv(os.path.join(results_dir, "pilot", "pilot_summary.csv"))
    r = rows[0]
    cells = [[label, style.fmt_int(r.get(col)) if count else style.fmt(r.get(col))]
             for col, label, count in METRICS]
    return style.write_table(out_dir, "T5", ["Metric", "Value"], cells, "User pilot (preliminary)")
