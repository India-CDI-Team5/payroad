"""Per-sample metrics of ml-design v5 §4.2 and the surcharge formula they are judged against."""
import numpy as np
import scipy.stats

WET_MM = 0.1


def abs_err_mean(y_hat, y):
    return abs(float(np.mean(y_hat)) - float(np.mean(y)))


def max_hit(y_hat, y, cell):
    """Same cell for the wettest point of y and of y_hat (first one on ties); None when y is dry."""
    if np.max(y) <= WET_MM:
        return None
    return bool(cell[np.argmax(y)] == cell[np.argmax(y_hat)])


def beta(r, s=0.0, coef=0.15, cap=0.5, w=0.5):
    return 1 + min(max(r - w * s, 0) * coef, cap)


def surcharge(r, s=0.0, coef=0.15, thr=1.2):
    return beta(r, s, coef) > thr


def coverage(y, lo, hi, mask):
    mask = np.asarray(mask, dtype=bool)
    inside = (np.asarray(lo) <= np.asarray(y)) & (np.asarray(y) <= np.asarray(hi))
    return float(inside[mask].mean()) if mask.any() else None


def spearman(a, b):
    return scipy.stats.spearmanr(a, b).statistic
