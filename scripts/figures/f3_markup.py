"""F3: median markup versus the number of bidding drivers, per bot config (results/sim/E1_summary.csv)."""
import os

import matplotlib.pyplot as plt

import style


def make(results_dir, out_dir):
    style.apply()
    rows = style.read_csv(os.path.join(results_dir, "sim", "E1_summary.csv"))
    fig, ax = plt.subplots(figsize=style.SINGLE)
    for c in style.CONFIGS:
        pts = sorted((int(r["n"]), r) for r in rows if r["config"] == c)
        if not pts:
            continue
        x = [p[0] for p in pts]
        color = style.CONFIG_COLORS[c]
        ax.plot(x, [float(p[1]["markup_median"]) for p in pts], color=color, marker="o",
                markersize=style.MARKER_SIZE, label=c)
        ax.fill_between(x, [float(p[1]["ci_lo"]) for p in pts], [float(p[1]["ci_hi"]) for p in pts],
                        color=color, alpha=0.15, linewidth=0)
    ax.set_xlabel("Number of bidding drivers")
    ax.set_ylabel("Median markup (final / base price)")
    ax.legend(frameon=False, ncol=2)
    return [style.save(fig, os.path.join(out_dir, "F3_markup.png"))]
