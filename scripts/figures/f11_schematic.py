"""F11 (schematic): how the three placement rules pick queries on one made-up route (paper-revision-v2 Y1).

A drawing of the rules, not data: the route (cell lengths in points) is invented so that each rule's behaviour is
visible at one budget k = 4. The rules are the real ones (weather.selection.select_b1 / select_b2 and the
post-hoc H-P rule of training.posthoc_placement), applied to the made-up cells; M2's variance step is drawn as
"largest remaining cells", which is what it does when every cell is wet (paper Ⅱ-3: the score is geometric).
Results stay in table 1.

    python scripts/figures/f11_schematic.py      # -> results/figures/F11_schematic.png
"""
import argparse
import math
import os
import sys

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import style  # noqa: E402

OUT = os.path.join(ROOT, "results", "figures", "F11_schematic.png")
CELL_POINTS = [2, 7, 13, 3, 5, 2]          # points per cell along the route; short cells at both ends
K = 4
COLORS = {"B1": style.METHOD_STYLE["B1"]["color"], "M2": "#000000", "Mid": "#CC79A7"}


def round_half_up(x):
    return int(math.floor(x + 0.5))


def cell_of_points(cell_points):
    return [c for c, n in enumerate(cell_points) for _ in range(n)]


def b1_points(P, k):
    """Same as weather.selection.select_b1: k points evenly spaced, both ends included."""
    return [round_half_up(i * (P - 1) / (k - 1)) for i in range(k)]


def end_anchored(cell_points, k):
    """M2 on an all-wet route: ceil(k/2) cells by the B2 rule (both ends), then the largest remaining cells."""
    U = len(cell_points)
    a = math.ceil(k / 2)
    chosen = [round_half_up(i * (U - 1) / (a - 1)) for i in range(a)] if a > 1 else [round_half_up((U - 1) / 2)]
    rest = sorted((c for c in range(U) if c not in chosen), key=lambda c: (-cell_points[c], c))
    return sorted(chosen + rest[:k - len(chosen)])


def segment_centre(cell_points, k):
    """H-P: the cell of the centre point of each of k equal blocks of points; a repeat takes the nearest other cell."""
    cells = cell_of_points(cell_points)
    P = len(cells)
    chosen = []
    for i in range(k):
        t = int(math.floor((i + 0.5) * P / k))
        if cells[t] not in chosen:
            chosen.append(cells[t])
            continue
        rest = [c for c in range(len(cell_points)) if c not in chosen]
        gap = [min(abs(j - t) for j, cj in enumerate(cells) if cj == c) for c in rest]
        chosen.append(rest[gap.index(min(gap))])
    return sorted(chosen)


def draw(path, cell_points=CELL_POINTS, k=K):
    style.apply()
    cells = cell_of_points(cell_points)
    P = len(cells)
    starts = [sum(cell_points[:c]) for c in range(len(cell_points))]
    pts = b1_points(P, k)
    pt_cells = [cells[p] for p in pts]
    rows = [
        ("B1", "B1", None, None),                                      # point-uniform (current)
        ("B2·M2", "M2", end_anchored(cell_points, k), None),          # end-anchored
        ("Mid", "Mid", segment_centre(cell_points, k), None),          # segment-centre (post hoc)
    ]

    fig, ax = plt.subplots(figsize=(2.15, 1.1))
    n = len(rows)
    for c, (s0, w) in enumerate(zip(starts, cell_points)):
        shade = "#d9d9d9" if c % 2 == 0 else "#f2f2f2"
        ax.add_patch(Rectangle((s0, -0.5), w, n + 0.9, facecolor=shade, linewidth=0, zorder=0))
        ax.text(s0 + w / 2, n + 0.15, str(w), ha="center", va="center", fontsize=7)
    ax.text(-0.5, n + 0.15, "pts/cell", ha="right", va="center", fontsize=6.5)

    for i, (label, key, chosen, note) in enumerate(rows):
        y = n - 1 - i
        if chosen is None:
            seen = set()
            for p, c in zip(pts, pt_cells):
                dup = c in seen
                seen.add(c)
                ax.plot(p + 0.5, y, marker="x" if dup else "o", color="#D55E00" if dup else COLORS[key],
                        markersize=4, markeredgewidth=1.2, linestyle="none", zorder=3)
        else:
            for c in chosen:
                ax.add_patch(Rectangle((starts[c] + 0.15, y - 0.28), cell_points[c] - 0.3, 0.56,
                                       facecolor=COLORS[key], alpha=0.85, linewidth=0, zorder=3))
    ax.set_yticks(range(n))
    ax.set_yticklabels([r[0] for r in reversed(rows)], fontsize=7.5)
    ax.set_xlim(0, P)
    ax.set_ylim(-0.6, n + 0.45)
    ax.set_xticks([0, P])
    ax.set_xticklabels(["start", "end"], fontsize=7)
    ax.tick_params(axis="y", length=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.text(P / 2, -0.95, "×: repeated cell", ha="center", va="top", fontsize=6.5, color="#D55E00")
    return style.save(fig, path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    print(draw(ap.parse_args(argv).out))


if __name__ == "__main__":
    main()
