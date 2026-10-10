"""T4: bargaining versus a fixed price (results/sim/E3_fixed.csv)."""
import os

import style

HEADER = ["Config", "Mode", "Match rate [95% CI]", "Median time to match (s)", "Mean winner pickup ETA (min)"]


def make(results_dir, out_dir):
    rows = style.read_csv(os.path.join(results_dir, "sim", "E3_fixed.csv"))
    cells = [[r["config"], r["mode"], style.fmt_ci(r["match_rate"], r["ci_lo"], r["ci_hi"]),
              style.fmt(r["time_to_match_median"]), style.fmt(r["winner_eta_mean"])] for r in rows]
    return style.write_table(out_dir, "T4", HEADER, cells, "Reverse-auction bargaining versus a fixed price")
