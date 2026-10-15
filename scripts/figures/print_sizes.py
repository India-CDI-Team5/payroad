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
JOBS = [(f1_curve, (2.6, 1.85)), (f10_offer, (2.9, 1.9))]   # F9 crowds at this width: the original is used


def main():
    os.makedirs(OUT, exist_ok=True)
    saved = style.SINGLE
    try:
        for module, size in JOBS:
            style.SINGLE = size
            for path in module.make(RESULTS, OUT):
                print(path)
    finally:
        style.SINGLE = saved


if __name__ == "__main__":
    main()
