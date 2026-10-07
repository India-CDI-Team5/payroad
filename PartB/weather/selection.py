"""Budgets and query positions of ml-design v5 §1.3 and §3.1 (round-half-up everywhere)."""
import numpy as np


def round_half_up(x):
    return int(np.floor(x + 0.5))


def budget(U, rho):
    return max(1, min(U, round_half_up(rho * U)))


def linspace_idx(n, k):
    if k == 1:
        return [round_half_up((n - 1) / 2)]
    return [round_half_up(i * (n - 1) / (k - 1)) for i in range(k)]


def select_b0(order):
    return [order[0]]


def select_b1(P, k):
    return linspace_idx(P, k)


def select_b2(order, k):
    return [order[i] for i in linspace_idx(len(order), k)]
