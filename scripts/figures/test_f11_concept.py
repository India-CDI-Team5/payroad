"""Run from the repository root: python -m pytest scripts/figures"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import f11_concept  # noqa: E402


def row(sid, subset, rho="0.5", k="3", err="0.1"):
    return {"sample_id": str(sid), "subset": subset, "rho": rho, "k": k, "abs_err": err}


def test_pick_example_takes_smallest_holdout_id_and_ignores_errors():
    rows = [row(9001, "HOLDOUT", err="0.9"), row(8005, "HOLDOUT", err="0.0"), row(10, "MAIN"),
            row(7000, "HOLDOUT", k="4"), row(6000, "HOLDOUT", rho="0.25")]
    assert f11_concept.pick_example(rows) == (8005, "HOLDOUT")
    flipped = [dict(r, abs_err="0.5") for r in rows]
    assert f11_concept.pick_example(flipped) == (8005, "HOLDOUT")


def test_pick_example_falls_back_to_main():
    assert f11_concept.pick_example([row(30, "MAIN"), row(12, "MAIN"), row(5, "HOLDOUT", k="2")]) == (12, "MAIN")


def test_pick_example_fails_without_a_match():
    with pytest.raises(ValueError):
        f11_concept.pick_example([row(1, "HOLDOUT", k="2")])
