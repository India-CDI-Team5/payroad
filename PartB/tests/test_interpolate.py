import numpy as np

from weather.interpolate import constant_fill, linear_fill, nearest_fill

S = np.array([0.0, 0.5, 1.0, 1.5, 2.0])


def test_nearest_fill_takes_closest_in_s_and_smaller_index_on_ties():
    y_hat = nearest_fill(S, [3, 1], [4.0, 2.0])      # unsorted input is fine
    # point 2 (s=1.0) is 0.5 km from both observations -> index 1 wins
    assert y_hat.tolist() == [2.0, 2.0, 2.0, 4.0, 4.0]


def test_linear_fill_interpolates_inside_and_holds_edges():
    y_hat = linear_fill(S, [1, 3], [2.0, 4.0])
    assert y_hat.tolist() == [2.0, 2.0, 3.0, 4.0, 4.0]


def test_observed_points_keep_their_values_and_negatives_clip_to_zero():
    obs_idx, obs_y = [0, 2, 4], [0.0, 1.0, 0.0]
    for fill in (nearest_fill, linear_fill):
        y_hat = fill(S, obs_idx, obs_y)
        assert y_hat[obs_idx].tolist() == obs_y
        assert (y_hat >= 0).all()
    assert linear_fill(S, [0, 4], [-1.0, 1.0]).tolist() == [0.0, 0.0, 0.0, 0.5, 1.0]


def test_constant_fill():
    assert constant_fill(3, 0.7).tolist() == [0.7, 0.7, 0.7]
    assert constant_fill(2, -0.2).tolist() == [0.0, 0.0]
