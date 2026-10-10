"""T1: main comparison of the seven methods (results/model_a/T1_table.csv, stats_tests.csv)."""
import os

import style

RHO_COLS = [(0.25, "mae_rho25"), (0.5, "mae_rho50"), (0.75, "mae_rho75")]
HEADER = ["Method", "MAE k/U=0.25", "MAE k/U=0.50 [95% CI]", "MAE k/U=0.75", "Max-cell hit",
          "Surcharge agreement", "Call saving vs B1"]
HELD_OUT = ["M1", "B1"]
ALPHA = 0.05


def _row(r, label, marks=()):
    cells = [label]
    for rho, col in RHO_COLS:
        v = style.fmt(r[col]) if rho != 0.5 else style.fmt_ci(r[col], r["ci50_lo"], r["ci50_hi"])
        cells.append(v + ("†" if rho in marks else ""))
    return cells + [style.fmt(r["max_hit_rho50"]), style.fmt(r["agree_rho50"]), style.fmt(r["saving_vs_B1"])]


def make(results_dir, out_dir):
    d = os.path.join(results_dir, "model_a")
    table = style.read_csv(os.path.join(d, "T1_table.csv"))
    tests = style.read_csv(os.path.join(d, "stats_tests.csv"))

    sig = [t for t in tests if "M1" in (t["a"], t["b"]) and t["p_holm"] != "" and float(t["p_holm"]) < ALPHA]
    marks = {float(t["rho"]) for t in sig}
    main = {r["method"]: r for r in table if r["subset"] == "MAIN"}
    held = {r["method"]: r for r in table if r["subset"] == "HOLDOUT"}

    rows = [_row(main[m], m, marks if m == "M1" else ()) for m in style.METHODS if m in main]
    rows += [_row(held[m], f"{m} (held-out routes)") for m in HELD_OUT if m in held]

    notes = ["MAE in mm/h. Max-cell hit and surcharge agreement at k/U = 0.5. Call saving: 1 − ρ_method / ρ_B1 "
             "at the MAE B1 reaches with k/U = 1.0 (– = not reached)."]
    if sig:
        parts = [f"{t['a']} − {t['b']} at k/U = {float(t['rho']):.2f}: mean diff {float(t['mean_diff']):+.3f}, "
                 f"p_holm = {float(t['p_holm']):.3f}" for t in sig]
        notes.append("† Holm-adjusted p < 0.05 in a paired test involving M1 (" + "; ".join(parts) + ").")
    return style.write_table(out_dir, "T1", HEADER, rows, "Route-mean precipitation MAE by method", notes)
