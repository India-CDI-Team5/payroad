"""F7 panel: the fare rows and the bid table cut out of the rider screenshot (paper-revision-v2, blind paper).

The blind paper has one column and no room for the whole screen, and the screen header shows the service name, which
the blind version must not. To keep the text readable in print (about 7 pt at 6 cm), only what the paper talks about
is kept: the base price row, the rain and weather-factor rows, and the bid table's price, pickup ETA and driver
columns. Pieces are cut and placed side by side or stacked; nothing is drawn or edited.

The boxes are fractions of the screenshot, taken from F7_demo.png (rider window 1280 x 800 at 2x, 2560 x 1600,
Chrome device toolbar, captured 2026-10-16 in rain); a new capture must use the same window size.

    python scripts/figures/f7_demo_panel.py [--src results/figures/F7_demo.png]   # -> F7_demo_panel.png
"""
import argparse
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "results", "figures", "F7_demo.png")
OUT = os.path.join(ROOT, "results", "figures", "F7_demo_panel.png")

W, H = 2560, 1600
ASPECT = W / H
# (left, top, right, bottom) as fractions of width and height
BASE_ROW = (1577 / W, 598 / H, 1949 / W, 637 / H)        # "Base price"
RAIN_ROWS = (1577 / W, 752 / H, 1949 / W, 834 / H)       # "Avg rain", "Weather factor"
BID_PRICE_ETA = (1569 / W, 1234 / H, 1939 / W, 1471 / H)  # bid table: Price, Pickup ETA (header + 3 bids)
BID_DRIVER = (2169 / W, 1234 / H, 2289 / W, 1471 / H)     # bid table: Driver
BOXES = (BASE_ROW, RAIN_ROWS, BID_PRICE_ETA, BID_DRIVER)
GAP = 16                                                  # white space between pieces, in screenshot pixels


def box(img, frac):
    w, h = img.size
    return img.crop((round(frac[0] * w), round(frac[1] * h), round(frac[2] * w), round(frac[3] * h)))


def stack(parts, vertical, gap):
    if vertical:
        size = (max(p.width for p in parts), sum(p.height for p in parts) + gap * (len(parts) - 1))
    else:
        size = (sum(p.width for p in parts) + gap * (len(parts) - 1), max(p.height for p in parts))
    out = Image.new("RGB", size, "white")
    at = 0
    for p in parts:
        out.paste(p, (0, at) if vertical else (at, 0))
        at += (p.height if vertical else p.width) + gap
    return out


def panel(img):
    w, h = img.size
    if abs(w / h - ASPECT) > 0.01:
        raise ValueError(f"screenshot is {w}x{h}; capture the rider window at 1280 x 800 (2x: 2560 x 1600)")
    img = img.convert("RGB")
    base, rain, price_eta, driver = (box(img, b) for b in BOXES)
    fare = stack([base, rain], vertical=True, gap=0)
    bids = stack([price_eta, driver], vertical=False, gap=0)          # one table: rule lines stay joined
    return stack([fare, bids], vertical=True, gap=GAP * h // H)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    panel(Image.open(args.src)).save(args.out, dpi=(300, 300))
    print(args.out)


if __name__ == "__main__":
    main()
