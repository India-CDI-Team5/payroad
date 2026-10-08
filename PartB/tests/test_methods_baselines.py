import numpy as np
import pytest

from weather.methods import run
from weather.metrics import abs_err_mean
from weather.oracle import RouteOracle

# Fake route: 8 points every 0.5 km, re-entering cell 5 at the end.
CELLS = np.array([5, 5, 7, 7, 7, 9, 5, 5])
Y = np.array([0.0, 0.2, 1.5, 2.5, 1.0, 4.0, 0.3, 0.1])
S = np.arange(8) * 0.5
T = np.arange(8) * 1.0


def oracle():
    return RouteOracle(CELLS, Y)


@pytest.mark.parametrize("method", ["B2", "B2-L"])
def test_cell_methods_are_exact_when_every_cell_is_queried(method):
    o = oracle()
    r = run(method, o, S, T, k=o.U)
    assert abs_err_mean(r.y_hat, Y) == 0
    assert np.array_equal(r.y_hat, Y)
    assert r.calls == 3


def test_b1_pays_for_asking_the_same_cell_twice():
    o = oracle()
    r = run("B1", o, S, T, k=2)                        # points 0 and 7, both in cell 5
    assert r.obs_idx.tolist() == [0, 7]
    assert r.calls == 2
    assert o.duplicate_rate([0, 7]) == 0.5


def test_b1_and_b1_l_share_points_but_not_interpolation():
    o = oracle()
    near, lin = run("B1", o, S, T, k=3), run("B1-L", o, S, T, k=3)
    assert near.obs_idx.tolist() == lin.obs_idx.tolist() == [0, 4, 7]
    assert near.calls == lin.calls == 3
    assert near.y_hat.tolist() == [0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.1, 0.1]   # s=1.0: tie -> point 0
    assert lin.y_hat[2] == pytest.approx(0.5)


def test_b2_with_one_cell_queries_the_middle_cell():
    r = run("B2", oracle(), S, T, k=1)
    assert r.obs_idx.tolist() == [2, 3, 4]               # cell 7
    assert r.calls == 1


def test_b0_uses_one_call_and_fills_with_the_observed_mean():
    r = run("B0", oracle(), S, T, k=3)
    assert r.calls == 1
    assert r.obs_idx.tolist() == [0, 1, 6, 7]
    assert r.y_hat[[0, 1, 6, 7]].tolist() == [0.0, 0.2, 0.3, 0.1]
    assert r.y_hat[[2, 3, 4, 5]] == pytest.approx([0.15] * 4)
