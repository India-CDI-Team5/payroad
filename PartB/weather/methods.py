"""The compared methods of ml-design v5 §3.1. This card has the baselines; M1 and M2 come in card B4."""
from dataclasses import dataclass

import numpy as np

from weather.interpolate import constant_fill, linear_fill, nearest_fill
from weather.selection import select_b0, select_b1, select_b2


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
        raise NotImplementedError("B4")
    raise ValueError(f"unknown method {method!r}")
