from training import adaptive_budget as ab


def steps(*sds):
    # (calls, m_hat, sd, cell_means)
    return [(i + 1, 0.1 * (i + 1), sd, [0.2] * (i + 1)) for i, sd in enumerate(sds)]


def test_stop_at_first_step_under_tau_and_last_step_otherwise():
    tr = steps(0.3, 0.12, 0.04, 0.01)
    assert ab.stop_at(tr, ab.RULES["A"](0.05))[0] == 3
    assert ab.stop_at(tr, ab.RULES["A"](0.001))[0] == 4          # never under tau: all cells
    assert ab.stop_at(steps(0.9), ab.RULES["A"](0.001))[0] == 1  # dry first cell: trajectory has one step


def test_range_rule_needs_two_cells():
    tr = [(1, 0.1, 0.5, [0.3]), (2, 0.1, 0.4, [0.3, 0.31]), (3, 0.1, 0.3, [0.3, 0.31, 0.9])]
    assert ab.stop_at(tr, ab.RULES["C-range"](0.05))[0] == 2


def test_tune_keeps_calls_at_or_under_target():
    val = [{"m": 0.0, "B": (2, 0.0), "traj": steps(0.3, 0.12, 0.04)} for _ in range(3)]
    ch = ab.tune(val)
    assert ch["target_calls"] == 2 and ch["A_val"][0] <= 2
    assert ch["tau"] > 0.12                                       # the largest-calls tau not over 2 calls
