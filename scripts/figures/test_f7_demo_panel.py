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
    for b in fp.BOXES:
        assert header < b[1] < b[3] <= 1 and 0 <= b[0] < b[2] <= 1


def test_panel_layout():
    out = fp.panel(Image.new("RGB", (2560, 1600), "red"))
    size = {name: (round(b[2] * 2560) - round(b[0] * 2560), round(b[3] * 1600) - round(b[1] * 1600))
            for name, b in zip(("base", "rain", "price_eta", "driver"), fp.BOXES)}
    fare_h = size["base"][1] + size["rain"][1]
    bids_w = size["price_eta"][0] + size["driver"][0]
    assert out.height == fare_h + fp.GAP + max(size["price_eta"][1], size["driver"][1])
    assert out.width == max(size["base"][0], bids_w)


def test_wrong_window_size_is_refused():
    with pytest.raises(ValueError):
        fp.panel(Image.new("RGB", (1920, 1080)))
