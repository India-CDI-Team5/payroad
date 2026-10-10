"""T2: surcharge decisions under other β coefficients (results/model_a/T2_beta_sensitivity.csv)."""
import os

import style

HEADER = ["c_β", "Method", "n", "Agreement", "Over-surcharge", "Under-surcharge", "Rank"]


def make(results_dir, out_dir):
    rows = style.read_csv(os.path.join(results_dir, "model_a", "T2_beta_sensitivity.csv"))
    cells = [[style.fmt(r["coef"], 2), r["method"], style.fmt_int(r["n"]), style.fmt(r["agree"]),
              style.fmt(r["over_rate"]), style.fmt(r["under_rate"]), style.fmt_int(r["rank"])] for r in rows]
    return style.write_table(out_dir, "T2", HEADER, cells, "Surcharge agreement by β coefficient",
                             ["Threshold β > 1.2 for every c_β. Rank by agreement within each c_β."])
