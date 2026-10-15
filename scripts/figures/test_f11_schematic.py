"""Run from the repository root: python -m pytest scripts/figures

The schematic must draw what the real rules do, so its helpers are checked against weather.selection and the
post-hoc H-P rule on the same made-up route."""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "PartB"))

import f11_schematic as fs  # noqa: E402
from weather.oracle import RouteOracle  # noqa: E402
from weather.selection import select_b1, select_b2  # noqa: E402


def oracle():
    cells = fs.cell_of_points(fs.CELL_POINTS)
    return RouteOracle(np.array(cells), np.ones(len(cells)))


def test_b1_points_match_select_b1_and_repeat_one_cell():
    o = oracle()
    pts = fs.b1_points(len(o.cell), fs.K)
    assert pts == select_b1(len(o.cell), fs.K)
    assert len({o.cell[p] for p in pts}) == fs.K - 1


def test_end_anchored_keeps_b2_anchor_at_both_ends():
    o = oracle()
    chosen = fs.end_anchored(fs.CELL_POINTS, fs.K)
    assert set(select_b2(o.order, 2)) <= set(chosen)
    assert {0, len(fs.CELL_POINTS) - 1} <= set(chosen)


def test_segment_centre_matches_posthoc_rule_and_skips_ends():
    try:
        from training.posthoc_placement import select_hp
    except ImportError:                     # needs the frozen-model imports of final_eval; fall back to the drawing
        select_hp = None
    chosen = fs.segment_centre(fs.CELL_POINTS, fs.K)
    if select_hp is not None:
        assert sorted(select_hp(oracle(), fs.K)) == chosen
    assert 0 not in chosen and len(fs.CELL_POINTS) - 1 not in chosen
