"""F9: (a) collusion detection on the pre-registered unseen strategy S4 (results/collusion/F9_S4.csv),
(b) how much a ring raises the markup under C1 (results/sim/E7_collusion.csv)."""
import os

import matplotlib.pyplot as plt

import style

E7_CONFIG = "C1"
# Above each panel, clear of its title, so no legend covers a line.
LEGEND = {"frameon": False, "fontsize": 6, "loc": "lower center", "bbox_to_anchor": (0.5, 1.12), "ncol": 2}


def _in_order(rows, key):
    seen = []
    for r in rows:
        if r[key] not in seen:
            seen.append(r[key])
    return seen


def _series(ax, rows, key, y, lo, hi):
    ax.set_xticks(sorted({float(r["ring_share"]) for r in rows}))
    for i, name in enumerate(_in_order(rows, key)):
        pts = sorted((float(r["ring_share"]), r) for r in rows if r[key] == name)
        style.errorbar(ax, [p[0] for p in pts], [float(p[1][y]) for p in pts], [float(p[1][lo]) for p in pts],
                       [float(p[1][hi]) for p in pts], name, style.SERIES_STYLE[i % len(style.SERIES_STYLE)])


def make(results_dir, out_dir):
    style.apply()
    f9 = style.read_csv(os.path.join(results_dir, "collusion", "F9_S4.csv"))
    e7 = [r for r in style.read_csv(os.path.join(results_dir, "sim", "E7_collusion.csv")) if r["config"] == E7_CONFIG]

    fig, (a, b) = plt.subplots(1, 2, figsize=style.SINGLE)
    _series(a, f9, "method", "pr_auc", "ci_lo", "ci_hi")
    a.set_xlabel("Collusion share")
    a.set_ylabel("PR-AUC (S4)")
    a.set_title("(a)", fontsize=8)
    a.legend(**LEGEND)

    _series(b, e7, "strategy", "delta_vs_0", "ci_lo", "ci_hi")
    b.axhline(0, color="#999999", linestyle=":", linewidth=1.0)
    b.set_xlabel("Collusion share")
    b.set_ylabel("Markup change vs no collusion")
    b.set_title(f"(b) {E7_CONFIG}", fontsize=8)
    b.legend(**LEGEND)
    fig.tight_layout()
    return [style.save(fig, os.path.join(out_dir, "F9_collusion.png"))]
