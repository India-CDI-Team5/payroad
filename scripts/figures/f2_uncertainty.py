"""F2: calibration of the GP intervals and error by predicted uncertainty (results/model_a/F2_*.csv, MAIN)."""
import os

import matplotlib.pyplot as plt

import style

BIN_METHOD, BIN_RHO = "M1", 0.5


def make(results_dir, out_dir):
    style.apply()
    d = os.path.join(results_dir, "model_a")
    coverage = style.read_csv(os.path.join(d, "F2_coverage.csv"))
    bins = style.read_csv(os.path.join(d, "F2_uncertainty_bins.csv"))
    spearman = style.read_csv(os.path.join(d, "F2_spearman.csv"))

    fig, (a, b) = plt.subplots(1, 2, figsize=style.SINGLE)
    for m in ("M1", "M2"):
        # rho = 1.0 reveals every cell: no interval, n = 0 and blank values.
        rows = sorted((float(r["rho"]), r) for r in coverage if r["method"] == m and r["cov_points"] != "")
        if not rows:
            continue
        s = style.METHOD_STYLE[m]
        x = [p[0] for p in rows]
        a.plot(x, [float(p[1]["cov_points"]) for p in rows], color=s["color"], marker=s["marker"],
               markersize=style.MARKER_SIZE, linestyle="-", label=f"{m} points")
        a.plot(x, [float(p[1]["cov_mean"]) for p in rows], color=s["color"], marker=s["marker"],
               markersize=style.MARKER_SIZE, linestyle="--", label=f"{m} route mean")
    a.axhline(0.95, color="#999999", linestyle=":", linewidth=1.0)
    a.set_xticks([0.25, 0.5, 0.75])
    a.set_xlabel("Query budget k/U")
    a.set_ylabel("95% interval coverage")
    a.set_title("(a)", fontsize=8)

    rows = sorted((int(r["bin"]), r) for r in bins if r["method"] == BIN_METHOD and float(r["rho"]) == BIN_RHO)
    mid = [(float(p[1]["s_lo"]) + float(p[1]["s_hi"])) / 2 for p in rows]
    s = style.METHOD_STYLE[BIN_METHOD]
    b.plot(mid, [float(p[1]["mean_abs_err"]) for p in rows], color=s["color"], marker=s["marker"],
           markersize=style.MARKER_SIZE, linestyle="-")
    rho_s = next((r["spearman"] for r in spearman if r["method"] == BIN_METHOD and float(r["rho"]) == BIN_RHO), None)
    title = "(b)" + (f" Spearman ρ = {float(rho_s):.2f}" if rho_s not in (None, "") else "")
    b.set_title(title, fontsize=8)
    b.set_xlabel("Predicted std s (mm/h)")
    b.set_ylabel("Mean |error| (mm/h)")
    fig.tight_layout()
    fig.legend(*a.get_legend_handles_labels(), loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False,
               fontsize=6)
    return [style.save(fig, os.path.join(out_dir, "F2_uncertainty.png"))]
