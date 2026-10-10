"""F8: match rate over offer TTL × round limit for C1 (results/sim/E4_heatmap.csv)."""
import os

import matplotlib.pyplot as plt

import style

CONFIG = "C1"


def make(results_dir, out_dir):
    style.apply()
    rows = [r for r in style.read_csv(os.path.join(results_dir, "sim", "E4_heatmap.csv")) if r["config"] == CONFIG]
    ttls = sorted({int(r["offer_ttl"]) for r in rows})
    limits = sorted({int(r["round_limit"]) for r in rows})
    cell = {(int(r["offer_ttl"]), int(r["round_limit"])): float(r["match_rate"]) for r in rows}
    grid = [[cell.get((t, l), float("nan")) for l in limits] for t in ttls]

    fig, ax = plt.subplots(figsize=style.SINGLE)
    im = ax.imshow(grid, cmap="viridis", origin="lower", aspect="auto")
    lo, hi = im.get_clim()
    for i, t in enumerate(ttls):
        for j, l in enumerate(limits):
            v = grid[i][j]
            if v == v:
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=7,
                        color="white" if v < (lo + hi) / 2 else "black")
    ax.set_xticks(range(len(limits)), [str(l) for l in limits])
    ax.set_yticks(range(len(ttls)), [str(t) for t in ttls])
    ax.set_xlabel("Round limit")
    ax.set_ylabel("Offer TTL (s)")
    fig.colorbar(im, ax=ax, label="Match rate")
    return [style.save(fig, os.path.join(out_dir, "F8_heatmap.png"))]
