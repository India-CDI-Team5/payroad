import numpy as np
import pytest

from weather.metrics import abs_err_mean, beta, coverage, max_hit, spearman, surcharge


def test_abs_err_mean():
    assert abs_err_mean(np.array([1.0, 3.0]), np.array([2.0, 4.0])) == 1.0


def test_beta_threshold_is_four_thirds_mm_per_hour():
    assert beta(4 / 3) == pytest.approx(1.2)
    assert surcharge(1.34) is True
    assert surcharge(1.33) is False
    assert beta(10.0) == 1.5                           # capped
    assert beta(-1.0) == 1.0
    assert beta(2.0, s=1.0) == pytest.approx(1 + 1.5 * 0.15)


def test_max_hit_compares_cells_of_first_maxima_and_skips_dry_samples():
    cell = np.array([5, 5, 7, 9])
    assert max_hit(np.array([0, 0, 0, 0.0]), np.array([0.05, 0, 0.1, 0]), cell) is None
    assert max_hit(np.array([1.0, 2.0, 0, 0]), np.array([2.0, 1.0, 0, 0]), cell) is True    # both cell 5
    assert max_hit(np.array([0, 0, 3.0, 0]), np.array([2.0, 1.0, 0, 0]), cell) is False
    assert max_hit(np.array([1.0, 1.0, 1.0, 1.0]), np.array([0, 0, 0, 0.5]), cell) is False  # tie -> first


def test_coverage_counts_only_masked_points():
    y = np.array([1.0, 2.0, 3.0, 4.0])
    lo, hi = np.array([0.5, 2.5, 2.0, 0.0]), np.array([1.5, 3.0, 3.0, 1.0])
    assert coverage(y, lo, hi, np.array([True, True, True, False])) == pytest.approx(2 / 3)
    assert coverage(y, lo, hi, np.zeros(4, dtype=bool)) is None


def test_spearman():
    assert spearman([1, 2, 3, 4], [10, 20, 25, 100]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
