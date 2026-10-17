"""F13: calls per request along the whole Hyderabad request stream, with each method's error (stream_calls.json).

Post-hoc description (training.stream_calls) of the pre-registered stream (docs/shared-gp-city.md, N = 20 per 10 min):
previous points, every cell once, every cell with the shared cache (error 0) and the shared GP. Drawn at print size.

    python scripts/figures/f13_stream_calls.py    # -> results/figures/print/F13_stream_calls.png
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import matplotlib.pyplot as plt  # noqa: E402

import style  # noqa: E402

SRC = os.path.join(ROOT, "results", "shared_gp_city", "stream_calls.json")
OUT = os.path.join(ROOT, "results", "figures", "print", "F13_stream_calls.png")
BARS = [("previous", "Prev.\npoints"), ("cell", "Each\ncell"), ("F", "Cell +\ncache"), ("G", "Shared\nGP")]
SIZE = (1.75, 1.05)                    # inches: + labels = the printed width (~5 cm), so 7 pt stays 7 pt


def make(src=SRC, out=OUT):
    style.apply()
    with open(src, encoding="utf-8") as f:
        d = json.load(f)
    calls = [d[k]["calls"] for k, _ in BARS]
    maes = [d[k]["mae"] for k, _ in BARS]
    fig, ax = plt.subplots(figsize=SIZE)
    x = list(range(len(BARS)))
    ax.bar(x, calls, width=0.62, color=["#bbbbbb", "#999999", "#666666", "#000000"])
    for xi, c, m in zip(x, calls, maes):
        ax.text(xi, c + 0.15, f"{c:.2f}\n({m:.3f})".replace("(0.000)", "(0)"), ha="center", va="bottom", fontsize=6)
    ax.set_xticks(x)
    ax.set_xticklabels([lab for _, lab in BARS], fontsize=6)
    ax.set_ylabel("Calls / request")
    ax.set_ylim(0, max(calls) * 1.45)
    return style.save(fig, out)


if __name__ == "__main__":
    print(make())
