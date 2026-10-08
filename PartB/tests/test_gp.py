import numpy as np
import pytest
import scipy.optimize

from weather.gp import KERNELS, features, fit, kernel, neg_log_marginal, posterior

KINDS = sorted({kind for kind, _ in KERNELS.values()})


def _route(n=40, step=0.5):
    s = np.arange(n) * step
    return s, s * 3.0            # 20 km/h -> 3 min per km


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("ard", [False, True])
def test_kernel_is_one_at_zero_symmetric_and_positive_semidefinite(kind, ard):
    s, t = _route()
    X = features(s, t, ard)
    ls = [4.0, 30.0] if ard else [4.0]
    K = kernel(kind, X, X, ls)
    assert np.allclose(np.diag(K), 1.0)
    assert np.allclose(K, K.T)
    assert np.linalg.eigvalsh(K).min() > -1e-9


@pytest.mark.parametrize("name", sorted(KERNELS))
def test_posterior_mean_goes_through_observations_with_tiny_noise(name):
    kind, ard = KERNELS[name]
    s, t = _route()
    obs = np.arange(0, 40, 3)
    z_o = np.sin(s[obs] / 3.0) + 0.5
    params = {"sigma_f": 1.0, "sigma_n": 1e-4, "ls_s": 4.0}
    if ard:
        params["ls_t"] = 30.0
    X = features(s, t, ard)
    mean, cov = posterior(X[obs], z_o, X, params, kind)
    assert np.max(np.abs(mean[obs] - z_o)) < 1e-3
    assert cov.shape == (40, 40)
    assert np.all(np.diag(cov) > -1e-9)
    assert np.all(np.diag(cov)[obs] < 1e-3)        # latent variance, no noise added


@pytest.mark.parametrize("name", sorted(KERNELS))
def test_likelihood_gradient_matches_finite_differences(name):
    kind, ard = KERNELS[name]
    rng = np.random.default_rng(1)
    s, t = _route(15)
    X = features(s, t, ard)
    data = [(X, z - z.mean()) for z in rng.normal(size=(3, 15))]
    theta = np.log([0.8, 0.1, 3.0] + ([20.0] if ard else []))
    from weather.gp import _nll_and_grad
    _, grad = _nll_and_grad(theta, data, kind, ard)
    num = scipy.optimize.approx_fprime(theta, neg_log_marginal, 1e-6, data, kind, ard)
    assert np.allclose(grad, num, rtol=1e-4, atol=1e-4)


def test_fit_recovers_length_scale_of_rbf_paths():
    rng = np.random.default_rng(0)
    s, t = _route(40)
    X = features(s, t, False)
    K = 1.0 * kernel("rbf", X, X, [10.0]) + 0.05 ** 2 * np.eye(40)
    L = np.linalg.cholesky(K + 1e-9 * np.eye(40))
    data = []
    for _ in range(300):
        z = L @ rng.standard_normal(40)
        data.append((X, z - z.mean()))
    params, nll, seconds = fit(data, "rbf", False)
    assert 5.0 <= params["ls_s"] <= 20.0
    assert np.isfinite(nll) and seconds > 0
