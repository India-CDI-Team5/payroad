import numpy as np
import pytest

from weather.stats import holm, week_bootstrap_ci, wilcoxon_pair


def test_holm_matches_the_hand_computation():
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert holm([0.5, 0.9]) == pytest.approx([1.0, 1.0])


def test_wilcoxon_pair_reports_n_median_and_p():
    rng = np.random.default_rng(0)
    a = rng.normal(1.0, 0.2, size=60)
    b = a - 0.3 + rng.normal(0, 0.05, size=60)
    n, med, p = wilcoxon_pair(a, b)
    assert n == 60 and med == pytest.approx(0.3, abs=0.05) and p < 1e-6
    assert wilcoxon_pair([1.0, 2.0], [1.0, 2.0]) == (2, 0.0, 1.0)


def test_week_bootstrap_is_reproducible_and_brackets_the_mean():
    rng = np.random.default_rng(1)
    data = {(2024, w): rng.normal(w * 0.1, 1.0, size=rng.integers(3, 9)).tolist() for w in range(1, 25)}
    first = week_bootstrap_ci(data, B=500, seed=42)
    assert week_bootstrap_ci(data, B=500, seed=42) == first
    assert week_bootstrap_ci(data, B=500, seed=43) != first
    mean, lo, hi = first
    pooled = np.concatenate([np.asarray(v) for v in data.values()]).mean()
    assert mean == pytest.approx(pooled)
    assert lo < mean < hi
