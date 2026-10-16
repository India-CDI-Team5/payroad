"""Print-size copies of the paper's plots, so axis text stays at about 7-8 pt on the page.

The frozen figures (make_all.py, MANIFEST.txt) are drawn 8.5 cm wide and the papers shrink them to 5.8-6.6 cm,
which takes 7 pt tick labels down to about 5 pt. This redraws the same plots, from the same CSVs and with the same
code, at the width they are printed, into results/figures/print/. make_all.py and its MANIFEST are not touched.

    python scripts/figures/print_sizes.py    # -> results/figures/print/F1_curve.png, F1_kabs.png, F10_offer.png
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import f1_curve  # noqa: E402
import f10_offer  # noqa: E402
import style  # noqa: E402

RESULTS = os.path.join(ROOT, "results")
OUT = os.path.join(RESULTS, "figures", "print")
# (module, figure size in inches = printed size): one panel 6.6 cm, two panels 7.4 cm.
# The drawn size excludes ~0.7 cm of axis labels that bbox="tight" adds, so a figure placed at W cm is drawn W - 0.7
# cm wide (2026-10-17: F1 is placed at 6.0 cm in the proceedings and 5.6 cm in the blind paper).
JOBS = [(f1_curve, (2.09, 1.3), ""), (f1_curve, (1.93, 1.2), "blind"),
        (f10_offer, (2.9, 1.9), "")]   # F9 crowds at this width: the original is used


def main():
    saved = style.SINGLE
    try:
        for module, size, sub in JOBS:
            out = os.path.join(OUT, sub)
            os.makedirs(out, exist_ok=True)
            style.SINGLE = size
            for path in module.make(RESULTS, out):
                print(path)
    finally:
        style.SINGLE = saved


if __name__ == "__main__":
    main()
