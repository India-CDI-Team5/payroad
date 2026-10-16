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
    val = [{"m": 0.0, "Bs": {0.5: (3, 0.0)}, "traj": steps(0.3, 0.12, 0.04)} for _ in range(3)]
    ch = ab.tune(val)
    assert abs(ch["target_calls"] - 2.91) < 1e-9 and ch["A_val"][0] <= 2.91
    assert ch["tau"] > 0.12                                       # 3 calls would exceed 0.97 x 3: stop at 2


def test_judge_primary_needs_holm_supporting_needs_direction():
    base = {"A_calls": 2.0, "B_calls": 2.0, "C_calls": 2.0}
    tests = [{"set": "temporal", "vs": "B", "p": 1e-4, "mean_diff": -0.01, **base},
             {"set": "temporal", "vs": "C", "p": 1e-3, "mean_diff": -0.01, **base},
             {"set": "MAIN", "vs": "B", "p": 0.2, "mean_diff": -0.01, **base},
             {"set": "MAIN", "vs": "C", "p": 0.2, "mean_diff": 0.001, **base}]
    assert not ab.judge(tests)                                    # MAIN A-C has the wrong direction
    tests[3]["mean_diff"] = -0.001
    assert ab.judge([{k: v for k, v in t.items() if k not in ("p_holm", "passed", "role", "calls_ok")} for t in tests])


def test_kappa():
    assert ab.kappa([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0
