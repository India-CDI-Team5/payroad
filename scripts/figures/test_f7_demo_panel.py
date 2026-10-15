"""Run from the repository root: python -m pytest scripts/figures

The blind paper's demo panel must never include the screen header (it shows the service name)."""
import os
import sys

import pytest
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import f7_demo_panel as fp  # noqa: E402


def test_boxes_stay_below_the_header_and_inside_the_screen():
    header = 80 / 1600                      # the brand bar is the top 80 px of the 2x capture
    for b in (fp.PRICE_ROWS, fp.BIDS):
        assert header < b[1] < b[3] <= 1 and 0 <= b[0] < b[2] <= 1


def test_panel_stacks_both_parts_with_a_gap():
    out = fp.panel(Image.new("RGB", (2560, 1600), "red"))
    h = lambda b: round(b[3] * 1600) - round(b[1] * 1600)  # noqa: E731
    assert out.height == h(fp.PRICE_ROWS) + h(fp.BIDS) + round(fp.GAP * 1600)
    assert out.width == round(fp.PRICE_ROWS[2] * 2560) - round(fp.PRICE_ROWS[0] * 2560)


def test_wrong_window_size_is_refused():
    with pytest.raises(ValueError):
        fp.panel(Image.new("RGB", (1920, 1080)))
