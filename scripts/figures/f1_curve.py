"""F1: route-mean precipitation MAE versus query budget (results/model_a/F1_curve.csv, F1_kabs.csv, MAIN).

Only B1, B2, M1 and M2 are drawn (paper-revision-v1 X6): B0, B1-L and B2-L stay in table 1 and the text, and
M2 is drawn last so it is on top. Post-hoc rules are not drawn; the figure shows pre-registered results only.
"""
import os

import matplotlib.pyplot as plt

import style

F1_METHODS = ["B1", "B2", "M1", "M2"]
CURVE_YLIM = (0, 0.22)      # B0 (0.27) would squeeze the rest; M1's upper CI at k/U = 0.25 is 0.21


def _draw(rows, xcol, xlabel, path, xticks=None, ylim=None):
    fig, ax = plt.subplots(figsize=style.SINGLE)
    for m in F1_METHODS:
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
    if ylim:
        ax.set_ylim(*ylim)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=4, frameon=False, handlelength=2.2)
    return style.save(fig, path)


def make(results_dir, out_dir):
    style.apply()
    curve = style.read_csv(os.path.join(results_dir, "model_a", "F1_curve.csv"))
    kabs = style.read_csv(os.path.join(results_dir, "model_a", "F1_kabs.csv"))
    return [
        _draw(curve, "rho", "Query budget k/U", os.path.join(out_dir, "F1_curve.png"), [0.25, 0.5, 0.75, 1.0],
              CURVE_YLIM),
        _draw(kabs, "k", "Query budget k (calls)", os.path.join(out_dir, "F1_kabs.png")),
    ]
