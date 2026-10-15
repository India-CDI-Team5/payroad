"""F7 panel: the deal summary and the bid list cut out of the rider screenshot (paper-revision-v2, blind paper).

The blind paper has one column and no room for the whole screen, and the screen header shows the service name, which
the blind version must not. This keeps two parts of the right-hand panel, stacked: the price rows (base price to
weather factor) and the bid table. Nothing is drawn or edited, only cut.

The boxes are fractions of the screenshot, taken from F7_demo.png (rider window 1280 x 800 at 2x, 2560 x 1600,
Chrome device toolbar, captured 2026-10-16 in rain);
a new capture must use the same window size.

    python scripts/figures/f7_demo_panel.py [--src results/figures/F7_demo.png]   # -> F7_demo_panel.png
"""
import argparse
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "results", "figures", "F7_demo.png")
OUT = os.path.join(ROOT, "results", "figures", "F7_demo_panel.png")

ASPECT = 2560 / 1600
# (left, top, right, bottom) as fractions of width and height
PRICE_ROWS = (0.613, 0.374, 0.985, 0.521)   # Base price ... Weather factor
BIDS = (0.613, 0.771, 0.985, 0.919)         # bid table header and three bids
GAP = 0.012                                 # white space between the two parts, as a fraction of height


def box(img, frac):
    w, h = img.size
    return img.crop((round(frac[0] * w), round(frac[1] * h), round(frac[2] * w), round(frac[3] * h)))


def panel(img):
    w, h = img.size
    if abs(w / h - ASPECT) > 0.01:
        raise ValueError(f"screenshot is {w}x{h}; capture the rider window at 1280 x 800 (2x: 2560 x 1600)")
    parts = [box(img.convert("RGB"), PRICE_ROWS), box(img.convert("RGB"), BIDS)]
    gap = round(GAP * h)
    out = Image.new("RGB", (max(p.width for p in parts), sum(p.height for p in parts) + gap), "white")
    out.paste(parts[0], (0, 0))
    out.paste(parts[1], (0, parts[0].height + gap))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    panel(Image.open(args.src)).save(args.out, dpi=(300, 300))
    print(args.out)


if __name__ == "__main__":
    main()
