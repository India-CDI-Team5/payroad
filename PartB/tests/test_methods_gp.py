import numpy as np
import pytest

from weather.methods import run, select_m2
from weather.metrics import abs_err_mean
from weather.oracle import RouteOracle

# Fake route: 12 points every 0.5 km over 6 cells, re-entering cell 1 at the end.
CELLS = np.array([1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 1])
Y = np.array([0.0, 0.2, 1.5, 2.5, 1.0, 4.0, 0.3, 0.1, 0.0, 0.6, 2.0, 0.4])
S = np.arange(12) * 0.5
T = np.arange(12) * 1.5


def model(transform="log1p", kernel="matern15", ard=False, kappa=1.0):
    params = {"sigma_f": 0.5, "sigma_n": 0.05, "ls_s": 1.5}
    if ard:
        params["ls_t"] = 10.0
    return {"kernel": kernel, "ard": ard, "transform": transform, "params": params, "kappa": kappa}


@pytest.mark.parametrize("method", ["M1", "M2"])
@pytest.mark.parametrize("transform", ["log1p", "identity"])
def test_gp_methods_are_exact_when_every_cell_is_queried(method, transform):
    o = RouteOracle(CELLS, Y)
    r = run(method, o, S, T, k=o.U, model=model(transform), sample_id=3, draws=20)
    assert abs_err_mean(r.y_hat, Y) == 0
    assert np.array_equal(r.y_hat, Y)
    assert r.calls == 6
    assert np.allclose(r.mean_draws, Y.mean())


@pytest.mark.parametrize("ard", [False, True])
def test_m2_positions_do_not_depend_on_the_values(ard):
    m = model(kernel="matern15" if not ard else "rbf", ard=ard)
    other = np.random.default_rng(5).gamma(0.5, 3.0, size=len(Y))
    for k in (2, 3, 4, 5):
        a = select_m2(RouteOracle(CELLS, Y), S, T, k, m)
        b = select_m2(RouteOracle(CELLS, other), S, T, k, m)
        assert a == b
        assert len(set(a)) == k
        ra = run("M2", RouteOracle(CELLS, Y), S, T, k, model=m)
        rb = run("M2", RouteOracle(CELLS, other), S, T, k, model=m)
        assert ra.obs_idx.tolist() == rb.obs_idx.tolist()


def test_m2_starts_from_the_b2_cells():
    o = RouteOracle(CELLS, Y)
    chosen = select_m2(o, S, T, 4, model())
    assert chosen[:2] == [1, 6]                     # ceil(4/2) = 2 cells by linspace over the first-appearance order


def test_m1_intervals_bracket_the_prediction_and_observed_points_are_exact():
    o = RouteOracle(CELLS, Y)
    r = run("M1", o, S, T, k=3, model=model(kappa=1.5))
    obs = r.obs_idx
    assert np.array_equal(r.y_hat[obs], Y[obs])
    assert np.array_equal(r.lo[obs], Y[obs]) and np.array_equal(r.hi[obs], Y[obs])
    assert np.all(r.lo <= r.y_hat + 1e-12) and np.all(r.y_hat <= r.hi + 1e-12)
    assert np.all(r.lo >= 0) and np.all(r.std_z[obs] == 0)
    wider = run("M1", o, S, T, k=3, model=model(kappa=3.0))
    unobs = np.setdiff1d(np.arange(len(Y)), obs)
    assert np.all(wider.std_z[unobs] == pytest.approx(2 * r.std_z[unobs]))


def test_draws_are_reproducible_per_sample_id():
    o = RouteOracle(CELLS, Y)
    a = run("M1", o, S, T, k=2, model=model(), sample_id=7, draws=50).mean_draws
    b = run("M1", o, S, T, k=2, model=model(), sample_id=7, draws=50).mean_draws
    c = run("M1", o, S, T, k=2, model=model(), sample_id=8, draws=50).mean_draws
    assert a.shape == (50,)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)
    assert np.all(a >= 0)


def test_gp_methods_need_a_model():
    with pytest.raises(ValueError):
        run("M1", RouteOracle(CELLS, Y), S, T, k=2)
