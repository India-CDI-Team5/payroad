"""F11: which cells each method queries on one held-out route at the same budget (paper-revision-v2 Y1).

An illustration, not a result: the route is chosen by a rule fixed before drawing (pick_example), never by how
the methods did on it. The averages stay in table 1. Post-hoc: reads results/posthoc/model_a/placement_per_sample
and PartB/data/{routes_holdout,routes,samples}.parquet, so run it where parquet can be read (Docker on this PC):

    MSYS_NO_PATHCONV=1 docker run --rm -v "<repo>:/repo" -w /repo payroad-partb-py \
        python scripts/figures/f11_concept.py

Not part of make_all: MANIFEST.txt is left as it is.
"""
import argparse
import csv
import gzip
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "PartB"))

import style  # noqa: E402

PER_SAMPLE = os.path.join(ROOT, "results", "posthoc", "model_a", "placement_per_sample.csv.gz")
DATA_DIR = os.path.join(ROOT, "PartB", "data")
OUT = os.path.join(ROOT, "results", "figures", "F11_concept.png")
RHO, K = "0.5", "3"
ROWS = [("B1", "B1 (points)"), ("M2", "M2"), ("H-P", "Mid (post hoc)")]
STEP_KM = 0.5
GAP_KM = 0.12


def pick_example(rows):
    """Smallest sample_id with rho = 0.5 and k = 3, held-out routes first, else main routes. Uses no errors."""
    for subset in ("HOLDOUT", "MAIN"):
        ids = {int(r["sample_id"]) for r in rows if r["subset"] == subset and r["rho"] == RHO and r["k"] == K}
        if ids:
            return min(ids), subset
    raise ValueError("no sample with rho = 0.5 and k = 3")


def read_per_sample(path=PER_SAMPLE):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_case(sample_id):
    """(cell ids, s_km, true precipitation) of one sample, read straight from the parquet files."""
    import pyarrow.parquet as pq

    sample = [r for r in pq.read_table(os.path.join(DATA_DIR, "samples.parquet")).to_pylist()
              if int(r["sample_id"]) == sample_id]
    if len(sample) != 1:
        raise ValueError(f"sample {sample_id}: found {len(sample)} rows")
    sample = sample[0]
    name = "routes_holdout.parquet" if sample["route_set"] == "holdout" else "routes.parquet"
    route = [r for r in pq.read_table(os.path.join(DATA_DIR, name), columns=["route_id", "cell", "s_km"]).to_pylist()
             if r["route_id"] == sample["route_id"]][0]
    return np.array(route["cell"]), np.array(route["s_km"], dtype=float), np.array(sample["gt_mm"], dtype=float)


def draw(cell, s, y, picks, path, show_error=True):
    """picks: {method: (queried cells or None, abs_err)}; B1 queries points, given by select_b1."""
    from weather.selection import select_b1

    style.apply()
    order = list(dict.fromkeys(cell.tolist()))                       # cells in order of first appearance
    shade = {c: ("#d9d9d9" if i % 2 == 0 else "#f2f2f2") for i, c in enumerate(order)}
    span = {c: (s[cell == c].min() - STEP_KM / 2, s[cell == c].max() + STEP_KM / 2) for c in order}

    fig, (top, bot) = plt.subplots(2, 1, figsize=(3.35, 2.6), sharex=True,
                                   gridspec_kw={"height_ratios": [1.1, 1.0], "hspace": 0.08})
    for c in order:
        for ax in (top, bot):
            ax.axvspan(*span[c], color=shade[c], zorder=0, linewidth=0)
        top.text(np.mean(span[c]), 1.0, f"{len(s[cell == c])}", transform=top.get_xaxis_transform(),
                 ha="center", va="bottom", fontsize=6)
    top.text(-0.02, 1.0, "points/cell", transform=top.transAxes, ha="right", va="bottom", fontsize=6)
    top.bar(s, y, width=STEP_KM * 0.9, color="#0072B2", zorder=2)
    top.set_ylabel("Rain (mm/h)")
    top.set_ylim(0, max(y.max() * 1.15, 0.1))

    n = len(ROWS)
    for i, (m, label) in enumerate(ROWS):
        yrow = n - 1 - i
        cells, err = picks[m]
        st = style.METHOD_STYLE.get(m, {"color": "#CC79A7", "marker": "s"})
        if m == "B1":
            idx = select_b1(len(s), int(K))
            bot.plot(s[idx], [yrow] * len(idx), linestyle="none", marker=st["marker"], color=st["color"],
                     markersize=4, zorder=3)
        else:
            for c in cells:                                            # inset so neighbouring cells stay apart
                bot.add_patch(plt.Rectangle((span[c][0] + GAP_KM, yrow - 0.3), span[c][1] - span[c][0] - 2 * GAP_KM, 0.6,
                                            facecolor=st["color"], alpha=0.85, zorder=3, linewidth=0))
        if show_error:
            bot.text(1.01, yrow, f"{err:.3f}", transform=bot.get_yaxis_transform(), va="center", fontsize=6)
    bot.set_yticks(range(n))
    bot.set_yticklabels([label for _, label in reversed(ROWS)])
    bot.set_ylim(-0.6, n - 0.4)
    bot.set_xlim(span[order[0]][0], span[order[-1]][1])
    bot.set_xlabel("Distance along route (km)")
    if show_error:
        bot.text(1.01, n - 0.45, "|err|", transform=bot.get_yaxis_transform(), va="bottom", fontsize=6)
    return style.save(fig, path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--no-error", action="store_true", help="leave out the per-method error column")
    args = ap.parse_args(argv)

    rows = read_per_sample()
    sample_id, subset = pick_example(rows)
    picks = {}
    for r in rows:
        if int(r["sample_id"]) == sample_id and r["rho"] == RHO and r["subset"] == subset and r["method"] in dict(ROWS):
            cells = [int(c) for c in r["cells"].split(";")] if r["cells"] else None
            picks[r["method"]] = (cells, float(r["abs_err"]))
    cell, s, y = load_case(sample_id)
    path = draw(cell, s, y, picks, args.out, show_error=not args.no_error)
    print(f"sample {sample_id} ({subset}), U = {len(set(cell.tolist()))}, P = {len(s)}: "
          + ", ".join(f"{m} {picks[m][1]:.4f}" for m, _ in ROWS) + f" -> {path}")


if __name__ == "__main__":
    main()
