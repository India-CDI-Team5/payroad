"""Tests and intervals of ml-design v5 §4.3: Wilcoxon signed-rank, Holm-Bonferroni, ISO-week block bootstrap."""
import numpy as np
import scipy.stats


def holm(pvals):
    """Holm-Bonferroni adjusted p-values, in the input order."""
    p = np.asarray(pvals, dtype=np.float64)
    m = len(p)
    order = np.argsort(p, kind="stable")
    adj = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p[i]))
        adj[i] = running
    return adj.tolist()


def wilcoxon_pair(err_a, err_b):
    """(n pairs, median of a − b, two-sided p). All-zero differences cannot be tested: p is reported as 1.0."""
    a, b = np.asarray(err_a, dtype=np.float64), np.asarray(err_b, dtype=np.float64)
    d = a - b
    if not np.any(d != 0):
        return len(d), 0.0, 1.0
    res = scipy.stats.wilcoxon(a, b, alternative="two-sided", zero_method="wilcox")
    return len(d), float(np.median(d)), float(res.pvalue)


def week_bootstrap_ci(values_by_week, B=2000, seed=42):
    """(mean, 2.5th, 97.5th percentile) of the pooled mean when whole ISO weeks are resampled with replacement."""
    weeks = sorted(values_by_week)
    blocks = [np.asarray(values_by_week[w], dtype=np.float64) for w in weeks]
    sums = np.array([b.sum() for b in blocks])
    counts = np.array([len(b) for b in blocks])
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(weeks), size=(B, len(weeks)))
    boot = sums[picks].sum(axis=1) / counts[picks].sum(axis=1)
    mean = float(sums.sum() / counts.sum())
    return mean, float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))
