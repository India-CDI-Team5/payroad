"""The compared methods of ml-design v5 §3.1: baselines B0-B2-L and the GP methods M1, M2.

model (M1, M2) = {"kernel", "ard", "transform", "params", "kappa"}, as stored in models/gp_interpolator.json.
"""
import math
from dataclasses import dataclass

import numpy as np

from weather.gp import TRANSFORMS, features, posterior
from weather.interpolate import constant_fill, linear_fill, nearest_fill
from weather.selection import select_b0, select_b1, select_b2

Z95 = 1.96
DRAW_JITTER = 1e-9
DRAW_SEED = 42                       # posterior draws use default_rng(42 + sample_id), ml-design v5 §5.1


@dataclass
class MethodResult:
    y_hat: np.ndarray
    calls: int
    obs_idx: np.ndarray
    std_z: np.ndarray = None
    lo: np.ndarray = None
    hi: np.ndarray = None
    mean_draws: np.ndarray = None


def run(method, oracle, s, t, k, model=None, sample_id=None, draws=0):
    P = len(s)
    if method == "B0":
        idx, y, calls = oracle.reveal_cells(select_b0(oracle.order))   # 1 call whatever k is
        y_hat = constant_fill(P, y.mean())
        y_hat[idx] = y
        return MethodResult(y_hat, calls, idx)
    if method in ("B1", "B1-L"):
        idx, y, calls = oracle.reveal_points(select_b1(P, k))
        fill = nearest_fill if method == "B1" else linear_fill
        return MethodResult(fill(s, idx, y), calls, idx)
    if method in ("B2", "B2-L"):
        idx, y, calls = oracle.reveal_cells(select_b2(oracle.order, k))
        fill = nearest_fill if method == "B2" else linear_fill
        return MethodResult(fill(s, idx, y), calls, idx)
    if method in ("M1", "M2"):
        if model is None:
            raise ValueError(f"{method} needs a model")
        cells = select_b2(oracle.order, k) if method == "M1" else select_m2(oracle, s, t, k, model)
        idx, y, calls = oracle.reveal_cells(cells)
        return gp_fill(s, t, idx, y, model, sample_id=sample_id, draws=draws, calls=calls)
    raise ValueError(f"unknown method {method!r}")


def select_m2(oracle, s, t, k, model):
    """ceil(k/2) cells by the B2 rule, then one at a time the unqueried cell whose points have the largest
    summed posterior variance (z space); ties go to the cell that appears first on the route.

    Only point positions are used, never values: with fixed hyperparameters the GP variance does not
    depend on the observations, so the whole set is known before any call (one multi-coordinate request).
    """
    kind = model["kernel"]
    X = features(s, t, model["ard"])
    chosen = list(select_b2(oracle.order, math.ceil(k / 2)))
    while len(chosen) < k:
        obs = np.nonzero(np.isin(oracle.cell, chosen))[0]
        rest = [c for c in oracle.order if c not in chosen]
        rest_pts = np.nonzero(np.isin(oracle.cell, rest))[0]
        _, cov = posterior(X[obs], np.zeros(len(obs)), X[rest_pts], model["params"], kind)
        var = np.diag(cov)
        scores = [var[oracle.cell[rest_pts] == c].sum() for c in rest]
        chosen.append(rest[int(np.argmax(scores))])                    # argmax keeps the first on ties
    return chosen


def gp_fill(s, t, obs_idx, obs_y, model, sample_id=None, draws=0, calls=None):
    """GP posterior (§3.2) at the unobserved points; observed points keep y. Intervals and draws use kappa."""
    P = len(s)
    g, g_inv = TRANSFORMS[model["transform"]]
    kappa = model.get("kappa", 1.0)
    obs_idx = np.asarray(obs_idx, dtype=int)
    obs_y = np.asarray(obs_y, dtype=np.float64)
    unobs = np.setdiff1d(np.arange(P), obs_idx)

    y_hat = np.zeros(P)
    y_hat[obs_idx] = obs_y
    std_z = np.zeros(P)
    lo, hi = y_hat.copy(), y_hat.copy()
    mean_draws = None
    if len(unobs) == 0:
        if draws > 0:
            mean_draws = np.full(draws, float(np.mean(y_hat)))
        return MethodResult(y_hat, calls, obs_idx, std_z, lo, hi, mean_draws)

    X = features(s, t, model["ard"])
    mean, cov = posterior(X[obs_idx], g(obs_y), X[unobs], model["params"], model["kernel"])
    sd = kappa * np.sqrt(np.maximum(np.diag(cov), 0.0))
    y_hat[unobs] = np.maximum(g_inv(mean), 0.0)
    std_z[unobs] = sd
    lo[unobs] = np.maximum(g_inv(mean - Z95 * sd), 0.0)
    hi[unobs] = np.maximum(g_inv(mean + Z95 * sd), 0.0)

    if draws > 0:
        if sample_id is None:
            raise ValueError("posterior draws need sample_id for their seed")
        rng = np.random.default_rng(DRAW_SEED + int(sample_id))
        L = np.linalg.cholesky(kappa ** 2 * cov + DRAW_JITTER * np.eye(len(unobs)))
        z = mean[None, :] + rng.standard_normal((draws, len(unobs))) @ L.T
        y_draws = np.maximum(g_inv(z), 0.0)
        mean_draws = (obs_y.sum() + y_draws.sum(axis=1)) / P
    return MethodResult(y_hat, calls, obs_idx, std_z, lo, hi, mean_draws)
