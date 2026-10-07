import numpy as np

from weather.oracle import RouteOracle

CELLS = [5, 5, 7, 7, 7, 9, 5, 5]          # re-enters cell 5 at the end
Y = [0.1, 0.2, 1.0, 1.1, 1.2, 3.0, 0.3, 0.4]


def test_order_is_first_appearance_and_U_counts_distinct_cells():
    o = RouteOracle(np.array(CELLS), np.array(Y))
    assert o.order == [5, 7, 9]
    assert o.U == 3


def test_reveal_cell_opens_every_point_of_that_cell_for_one_call():
    o = RouteOracle(np.array(CELLS), np.array(Y))
    idx, y, calls = o.reveal_cells([5])
    assert idx.tolist() == [0, 1, 6, 7]
    assert y.tolist() == [0.1, 0.2, 0.3, 0.4]
    assert calls == 1
    idx, _, calls = o.reveal_cells([9, 5, 9])
    assert idx.tolist() == [0, 1, 5, 6, 7] and calls == 2
    assert o.points_of(7).tolist() == [2, 3, 4]


def test_reveal_points_counts_every_request_even_duplicates():
    o = RouteOracle(np.array(CELLS), np.array(Y))
    idx, y, calls = o.reveal_points([6, 2, 2])
    assert idx.tolist() == [2, 6]
    assert y.tolist() == [1.0, 0.3]
    assert calls == 3


def test_duplicate_rate():
    o = RouteOracle(np.array(CELLS), np.array(Y))
    assert o.duplicate_rate([0, 7]) == 0.5           # both in cell 5
    assert o.duplicate_rate([0, 2, 5]) == 0.0
    assert o.duplicate_rate([0, 1, 6, 2]) == 0.5     # 4 calls, 2 cells
