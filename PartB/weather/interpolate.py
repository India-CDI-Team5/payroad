"""Fill a whole route profile from the observed points, along the distance axis s (km).

Observed points always keep their observed value, and predictions below 0 are clipped to 0.
"""
import numpy as np


def _finish(y_hat, obs_idx, obs_y):
    y_hat[obs_idx] = obs_y
    return np.maximum(y_hat, 0.0)


def _sorted(obs_idx, obs_y):
    obs_idx = np.asarray(obs_idx, dtype=int)
    order = np.argsort(obs_idx, kind="stable")
    return obs_idx[order], np.asarray(obs_y, dtype=np.float64)[order]


def nearest_fill(s, obs_idx, obs_y):
    """Value of the observed point closest in s; on a tie the one with the smaller index."""
    s = np.asarray(s, dtype=np.float64)
    obs_idx, obs_y = _sorted(obs_idx, obs_y)
    nearest = np.argmin(np.abs(s[:, None] - s[obs_idx][None, :]), axis=1)   # argmin keeps the first
    return _finish(obs_y[nearest], obs_idx, obs_y)


def linear_fill(s, obs_idx, obs_y):
    """Linear in s between observed points; beyond the ends, the edge value."""
    s = np.asarray(s, dtype=np.float64)
    obs_idx, obs_y = _sorted(obs_idx, obs_y)
    return _finish(np.interp(s, s[obs_idx], obs_y), obs_idx, obs_y)


def constant_fill(P, value):
    return np.maximum(np.full(P, value, dtype=np.float64), 0.0)
