"""F1: route-mean precipitation MAE versus query budget (results/model_a/F1_curve.csv, F1_kabs.csv, MAIN)."""
import os

import matplotlib.pyplot as plt

import style


def _draw(rows, xcol, xlabel, path, xticks=None):
    fig, ax = plt.subplots(figsize=style.SINGLE)
    for m in style.METHODS:
        pts = sorted((float(r[xcol]), r) for r in rows if r["subset"] == "MAIN" and r["method"] == m)
        if not pts:
            continue
        x = [p[0] for p in pts]
        style.errorbar(ax, x, [float(p[1]["mae"]) for p in pts], [float(p[1]["ci_lo"]) for p in pts],
                       [float(p[1]["ci_hi"]) for p in pts], m, style.METHOD_STYLE[m])
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Route-mean precipitation MAE (mm/h)")
    if xticks:
        ax.set_xticks(xticks)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=4, frameon=False, handlelength=2.2)
    return style.save(fig, path)


def make(results_dir, out_dir):
    style.apply()
    curve = style.read_csv(os.path.join(results_dir, "model_a", "F1_curve.csv"))
    kabs = style.read_csv(os.path.join(results_dir, "model_a", "F1_kabs.csv"))
    return [
        _draw(curve, "rho", "Query budget k/U", os.path.join(out_dir, "F1_curve.png"), [0.25, 0.5, 0.75, 1.0]),
        _draw(kabs, "k", "Query budget k (calls)", os.path.join(out_dir, "F1_kabs.png")),
    ]
