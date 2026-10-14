"""F10 (post hoc, paper-revision-v1 X4/X6): median markup and match rate versus the number of bidding drivers when
the rider bot's first offer is 0.80 (frozen E1), 0.90 or 1.00 times the base price, config C1.

Inputs: results/sim/E1_summary.csv (0.80) and results/posthoc/sim/ob090|ob100/E1_summary.csv (summarize.py e1).
"""
import os

import matplotlib.pyplot as plt

import style

CONFIG = "C1"
LEVELS = [("0.80", ("sim",)), ("0.90", ("posthoc", "sim", "ob090")), ("1.00", ("posthoc", "sim", "ob100"))]
LEGEND = {"frameon": False, "fontsize": 6, "loc": "upper center", "bbox_to_anchor": (0.5, 1.0), "ncol": 3}


def _panel(ax, series, y, lo, hi, ylabel, title):
    for i, (level, pts) in enumerate(series):
        s = style.SERIES_STYLE[i]
        x = [p[0] for p in pts]
        ax.plot(x, [float(p[1][y]) for p in pts], color=s["color"], linestyle=s["linestyle"], marker=s["marker"],
                markersize=style.MARKER_SIZE, label=f"First offer {level}")
        ax.fill_between(x, [float(p[1][lo]) for p in pts], [float(p[1][hi]) for p in pts], color=s["color"],
                        alpha=0.15, linewidth=0)
    ax.set_xlabel("Bidding drivers")
    ax.set_ylabel(ylabel)
    ax.set_xticks([1, 4, 7, 10])
    ax.set_title(title, fontsize=8)


def make(results_dir, out_dir):
    style.apply()
    series = []
    for level, parts in LEVELS:
        rows = style.read_csv(os.path.join(results_dir, *parts, "E1_summary.csv"))
        series.append((level, sorted((int(r["n"]), r) for r in rows if r["config"] == CONFIG)))
    fig, (a, b) = plt.subplots(1, 2, figsize=style.SINGLE)
    _panel(a, series, "markup_median", "ci_lo", "ci_hi", "Median markup", "(a) Median markup")
    _panel(b, series, "match_rate", "mr_ci_lo", "mr_ci_hi", "Match rate", "(b) Match rate")
    handles, labels = a.get_legend_handles_labels()
    fig.legend(handles, labels, **LEGEND)          # one legend for both panels, above them
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    return [style.save(fig, os.path.join(out_dir, "F10_offer.png"))]
