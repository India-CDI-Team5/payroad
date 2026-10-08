"""GP interpolation along a route (ml-design v5 §3.2, §3.3), in numpy/scipy only.

Hyperparameters are fitted to the sum of per-sample log marginal likelihoods, which
sklearn.gaussian_process cannot do, so the likelihood and its gradient are written out here.

params: {"sigma_f", "sigma_n", "ls_s"} plus "ls_t" for the ARD (s, t) kernels.
"""
import time

import numpy as np
import scipy.linalg
import scipy.optimize

# name -> (kernel kind, ARD over (s, t))
KERNELS = {
    "K1": ("rbf", False),
    "K2": ("matern05", False),
    "K3": ("matern15", False),
    "K4": ("matern25", False),
    "K5": ("matern15", True),
    "K6": ("rbf", True),
}


def _identity(x):
    return np.asarray(x, dtype=np.float64)


# name -> (forward g, inverse g^-1)
TRANSFORMS = {"log1p": (np.log1p, np.expm1), "identity": (_identity, _identity)}

JITTER = 1e-9
BOUNDS = {"sigma_f": (1e-3, 10.0), "sigma_n": (1e-4, 1.0), "ls_s": (0.5, 200.0), "ls_t": (1.0, 600.0)}
INIT_LS_S = (2.0, 8.0, 16.0, 32.0, 64.0)
INIT = {"sigma_f": 1.0, "sigma_n": 0.05, "ls_t": 30.0}


def features(s, t, ard):
    """Kernel inputs: (s, t) columns for ARD kernels, else s alone."""
    s = np.asarray(s, dtype=np.float64)
    if ard:
        return np.column_stack([s, np.asarray(t, dtype=np.float64)])
    return s[:, None]


def _scaled_sq(X1, X2, ls):
    """Per-axis squared differences divided by the length scales, shape (n1, n2, d)."""
    diff = (np.asarray(X1)[:, None, :] - np.asarray(X2)[None, :, :]) / np.asarray(ls, dtype=np.float64)
    return diff * diff


def _from_r2(kind, r2):
    """(k, g) at r = sqrt(r2), where dk/dlog(ls_d) = g · (Δ_d / ls_d)² for each axis d."""
    r = np.sqrt(r2)
    if kind == "rbf":
        k = np.exp(-0.5 * r2)
        return k, k
    if kind == "matern05":
        k = np.exp(-r)
        with np.errstate(divide="ignore", invalid="ignore"):
            g = np.where(r > 0, k / np.where(r > 0, r, 1.0), 0.0)
        return k, g
    if kind == "matern15":
        a = np.sqrt(3.0)
        e = np.exp(-a * r)
        return (1.0 + a * r) * e, a * a * e
    if kind == "matern25":
        a = np.sqrt(5.0)
        e = np.exp(-a * r)
        return (1.0 + a * r + a * a * r2 / 3.0) * e, (a * a / 3.0) * (1.0 + a * r) * e
    raise ValueError(f"unknown kernel kind {kind!r}")


def kernel(kind, X1, X2, ls):
    """Unit-variance kernel matrix; r = Euclidean distance after dividing each axis by its length."""
    return _from_r2(kind, _scaled_sq(X1, X2, ls).sum(axis=2))[0]


def _ls(params):
    return [params["ls_s"]] + ([params["ls_t"]] if "ls_t" in params else [])


def _names(ard):
    return ["sigma_f", "sigma_n", "ls_s"] + (["ls_t"] if ard else [])


def _to_params(theta_log, ard):
    return {n: float(np.exp(v)) for n, v in zip(_names(ard), theta_log)}


def _nll_and_grad(theta_log, datasets, kind, ard):
    p = _to_params(theta_log, ard)
    ls = np.array(_ls(p))
    sf2, sn2 = p["sigma_f"] ** 2, p["sigma_n"] ** 2
    nll = 0.0
    grad = np.zeros(len(theta_log))
    for X, z in datasets:
        n = len(z)
        sq = _scaled_sq(X, X, ls)
        k, g = _from_r2(kind, sq.sum(axis=2))
        K = sf2 * k + (sn2 + JITTER) * np.eye(n)
        c = scipy.linalg.cho_factor(K, lower=True)
        alpha = scipy.linalg.cho_solve(c, z)
        nll += 0.5 * z @ alpha + np.sum(np.log(np.diag(c[0]))) + 0.5 * n * np.log(2 * np.pi)
        # dNLL/dθ = 0.5 tr((K^-1 − α αᵀ) dK/dθ)
        W = scipy.linalg.cho_solve(c, np.eye(n)) - np.outer(alpha, alpha)
        grad[0] += 0.5 * np.sum(W * (2.0 * sf2 * k))
        grad[1] += 0.5 * np.trace(W) * 2.0 * sn2
        for d in range(len(ls)):
            grad[2 + d] += 0.5 * np.sum(W * (sf2 * g * sq[:, :, d]))
    return nll, grad


def neg_log_marginal(theta_log, datasets, kind, ard):
    """Σ_i −log p(z_i − μ_i | θ) over datasets [(X, z − mean(z)), …]; θ = log(sigma_f, sigma_n, ls_s[, ls_t])."""
    return _nll_and_grad(theta_log, datasets, kind, ard)[0]


def fit(datasets, kind, ard):
    """L-BFGS-B over log parameters from five starts; returns (params, nll, seconds) of the best."""
    start = time.perf_counter()
    names = _names(ard)
    bounds = [tuple(np.log(BOUNDS[n])) for n in names]
    best = None
    for ls_s in INIT_LS_S:
        x0 = np.log([{**INIT, "ls_s": ls_s}[n] for n in names])
        res = scipy.optimize.minimize(_nll_and_grad, x0, args=(datasets, kind, ard), jac=True,
                                      method="L-BFGS-B", bounds=bounds)
        if best is None or res.fun < best.fun:
            best = res
    return _to_params(best.x, ard), float(best.fun), time.perf_counter() - start


def posterior(X_o, z_o, X_s, params, kind):
    """Posterior mean and covariance of the latent function at X_s (no observation noise in cov).

    Mean μ = mean(z_o) (plug-in constant), K_oo carries sigma_n² on its diagonal.
    """
    z_o = np.asarray(z_o, dtype=np.float64)
    ls = _ls(params)
    sf2, sn2 = params["sigma_f"] ** 2, params["sigma_n"] ** 2
    mu = float(np.mean(z_o))
    K_oo = sf2 * kernel(kind, X_o, X_o, ls) + (sn2 + JITTER) * np.eye(len(z_o))
    K_so = sf2 * kernel(kind, X_s, X_o, ls)
    c = scipy.linalg.cho_factor(K_oo, lower=True)
    mean = mu + K_so @ scipy.linalg.cho_solve(c, z_o - mu)
    cov = sf2 * kernel(kind, X_s, X_s, ls) - K_so @ scipy.linalg.cho_solve(c, K_so.T)
    return mean, cov
