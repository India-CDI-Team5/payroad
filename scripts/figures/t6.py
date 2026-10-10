"""T6: collusion detection on unseen strategies (results/collusion/T6_S4.csv, T6_S5.csv)."""
import os

import style

STRATEGIES = ["S4", "S5"]
HEADER = ["Strategy", "Method", "n", "PR-AUC [95% CI]", "Recall at threshold", "FPR at threshold",
          "FPR at 80% recall"]


def make(results_dir, out_dir):
    d = os.path.join(results_dir, "collusion")
    found = {s: os.path.join(d, f"T6_{s}.csv") for s in STRATEGIES if os.path.exists(os.path.join(d, f"T6_{s}.csv"))}
    if not found:
        raise FileNotFoundError(os.path.join(d, "T6_S4.csv"))
    cells = []
    for s, path in found.items():
        for r in style.read_csv(path):
            cells.append([s, r["method"], style.fmt_int(r["n"]), style.fmt_ci(r["pr_auc"], r["ci_lo"], r["ci_hi"]),
                          style.fmt(r["recall_at_thr"]), style.fmt(r["fpr_at_thr"]), style.fmt(r["fpr_at_recall80"])])
    notes = [f"Missing: {', '.join(s for s in STRATEGIES if s not in found)}."] if len(found) < len(STRATEGIES) else []
    return style.write_table(out_dir, "T6", HEADER, cells, "Collusion detection on strategies unseen in training",
                             notes)
