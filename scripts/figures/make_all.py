"""Every figure (PNG) and table (markdown + CSV) of the paper from results/**/*.csv (card E1).

Run from the repository root:  python scripts/figures/make_all.py
Items whose input CSV is missing are skipped and listed at the end. SHA-256 of every file written
goes to <fig-dir>/MANIFEST.txt.
"""
import argparse
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import style  # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
RESULTS = os.path.join(ROOT, "results")
# (id, module, kind): figures go to the figure directory, tables to the table directory.
ITEMS = [
    ("F1", "f1_curve", "figure"),
    ("F2", "f2_uncertainty", "figure"),
    ("F3", "f3_markup", "figure"),
    ("F4", "f4_rounds", "figure"),
    ("F8", "f8_heatmap", "figure"),
    ("F9", "f9_collusion", "figure"),
    ("F10", "f10_offer", "figure"),
    ("T1", "t1", "table"),
    ("T2", "t2", "table"),
    ("T3", "t3", "table"),
    ("T4", "t4", "table"),
    ("T5", "t5", "table"),
    ("T6", "t6", "table"),
]


def make_all(results_dir=RESULTS, fig_dir=None, table_dir=None, log=print):
    """Returns (written paths, skipped [(id, missing file)])."""
    fig_dir = fig_dir or os.path.join(results_dir, "figures")
    table_dir = table_dir or os.path.join(results_dir, "tables")
    written, skipped = [], []
    for item_id, module, kind in ITEMS:
        mod = importlib.import_module(module)
        try:
            paths = mod.make(results_dir, fig_dir if kind == "figure" else table_dir)
        except FileNotFoundError as e:
            skipped.append((item_id, os.path.relpath(str(e.filename or e.args[0]), results_dir)))
            continue
        written += paths
        log(f"{item_id}: " + ", ".join(os.path.basename(p) for p in paths))

    os.makedirs(fig_dir, exist_ok=True)
    manifest = os.path.join(fig_dir, "MANIFEST.txt")
    base = os.path.dirname(os.path.normpath(fig_dir))
    with open(manifest, "w", encoding="utf-8", newline="\n") as f:
        for p in sorted(written, key=lambda p: os.path.relpath(p, base)):
            f.write(f"{style.sha256(p)}  {os.path.relpath(p, base).replace(os.sep, '/')}\n")
    log("skipped: " + (", ".join(f"{i} ({m})" for i, m in skipped) if skipped else "none"))
    return written, skipped


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--results-dir", default=RESULTS)
    p.add_argument("--fig-dir", default=None, help="default <results-dir>/figures")
    p.add_argument("--table-dir", default=None, help="default <results-dir>/tables")
    a = p.parse_args()
    make_all(a.results_dir, a.fig_dir, a.table_dir)


if __name__ == "__main__":
    main()
