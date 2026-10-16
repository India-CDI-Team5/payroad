"""F12: shared spatial GP vs. non-GP rules at matched calls, by request rate (results/shared_gp_city/summary.json).

Hyderabad, pre-registered (docs/shared-gp-city.md): every method spends 0.5 x the full-cache calls per request.
N = 20 requests per 10 min is the tested setting; the other rates are descriptive. Drawn at print size.

    python scripts/figures/f12_shared_gp.py    # -> results/figures/print/F12_shared_gp.png
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import matplotlib.pyplot as plt  # noqa: E402

import style  # noqa: E402

SRC = os.path.join(ROOT, "results", "shared_gp_city", "summary.json")
OUT = os.path.join(ROOT, "results", "figures", "print", "F12_shared_gp.png")
RATES = [5, 10, 20, 50]
SERIES = [("P", "P", style.SERIES_STYLE[1]),
          ("N", "N", style.SERIES_STYLE[2]),
          ("G", "G (shared GP)", {**style.SERIES_STYLE[0], "linewidth": 2.0})]
SIZE = (2.0, 1.45)                     # inches = the printed width (5.1 cm), so 7 pt stays 7 pt


def series(runs, key):
    return [runs[f"N{n}_f0.5"][key]["mae"] for n in RATES]


def make(src=SRC, out=OUT):
    style.apply()
    with open(src, encoding="utf-8") as f:
        runs = json.load(f)["runs"]
    fig, ax = plt.subplots(figsize=SIZE)
    x = list(range(len(RATES)))
    for key, label, st in SERIES:
        ax.plot(x, series(runs, key), label=label, markersize=style.MARKER_SIZE, **st)
    ax.axvspan(1.6, 2.4, color="#eeeeee", zorder=0)
    ax.text(2, 0.004, "tested", ha="center", va="bottom", fontsize=6, color="#555555")
    ax.set_xticks(x)
    ax.set_xticklabels([str(n) for n in RATES])
    ax.set_xlabel("Requests per 10 min (same calls)")
    ax.set_ylabel("MAE (mm/h)")
    ax.set_ylim(0, 0.105)
    h, l = ax.get_legend_handles_labels()
    ax.legend(h[::-1], l[::-1], loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3, frameon=False, fontsize=7,
              handlelength=1.5, columnspacing=0.6, handletextpad=0.3)
    return style.save(fig, out)


if __name__ == "__main__":
    print(make())
