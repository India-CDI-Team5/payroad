import pytest

from weather.selection import budget, linspace_idx, round_half_up, select_b0, select_b1, select_b2

RHOS = (0.25, 0.5, 0.75, 1.0)


@pytest.mark.parametrize("U, expected", [(3, [1, 2, 2, 3]), (8, [2, 4, 6, 8]), (1, [1, 1, 1, 1])])
def test_budget_table(U, expected):
    assert [budget(U, rho) for rho in RHOS] == expected


def test_round_half_up_rounds_halves_up_not_to_even():
    assert [round_half_up(x) for x in (0.5, 1.5, 2.5, 2.49)] == [1, 2, 3, 2]


def test_linspace_idx():
    assert linspace_idx(8, 1) == [4]                 # round_half_up(3.5)
    assert linspace_idx(8, 2) == [0, 7]
    assert linspace_idx(8, 3) == [0, 4, 7]           # 3.5 -> 4
    assert linspace_idx(1, 1) == [0]


def test_select_rules():
    order = [5, 7, 9]
    assert select_b0(order) == [5]
    assert select_b1(8, 3) == [0, 4, 7]
    assert select_b2(order, 1) == [7]
    assert select_b2(order, 2) == [5, 9]
    assert select_b2(order, 3) == [5, 7, 9]


def test_select_b2_never_repeats_a_cell_when_k_le_U():
    for U in range(1, 16):
        order = list(range(100, 100 + U))
        for k in range(1, U + 1):
            assert len(set(select_b2(order, k))) == k
