"""Run from the repository root: python -m pytest scripts/sim"""
import csv
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

_spec = importlib.util.spec_from_file_location("diagnostics", Path(__file__).with_name("diagnostics.py"))
dg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dg)

COLUMNS = ["run_id", "status", "markup", "winner_pickup_eta", "beta", "base_price", "distance_km"]


def write_deals(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})


def row(markup, status="MATCHED", eta=1.0, beta=1.0, base=200.0, dist=5.0):
    return {"status": status, "markup": markup, "winner_pickup_eta": eta, "beta": beta,
            "base_price": base, "distance_km": dist}


def test_read_matched_keeps_only_matched(tmp_path):
    p = tmp_path / "d.csv"
    write_deals(p, [row(1.1), row(1.2, status="EXPIRED"), row(0.9)])
    assert [r["markup"] for r in dg.read_matched(p)] == ["1.1", "0.9"]


def test_var_test_uses_sample_std_and_threshold():
    rows = [{"markup": str(m)} for m in (1.0, 1.02, 1.04)]
    v = dg.var_test(rows)
    assert v["n"] == 3
    assert v["std_markup"] == pytest.approx(0.02)
    assert v["pass"] is True
    assert dg.var_test([{"markup": "1.1"}] * 5)["pass"] is False


def test_r2_test_perfect_fit_fails_and_drops_missing_eta():
    rng = np.random.default_rng(0)
    rows = []
    for _ in range(50):
        eta, beta, base, dist = rng.uniform(1, 10), rng.uniform(1, 1.5), rng.uniform(100, 400), rng.uniform(1, 30)
        m = 0.5 + 0.01 * eta + 0.3 * beta + 0.001 * base + 0.002 * dist
        rows.append({k: str(v) for k, v in row(m, eta=eta, beta=beta, base=base, dist=dist).items()})
    rows.append({k: str(v) for k, v in row(5.0, eta="").items()})
    r = dg.r2_test(rows)
    assert r["n"] == 50
    assert r["r2"] == pytest.approx(1.0)
    assert r["pass"] is False and r["healthy"] is False


def test_r2_test_matches_numpy_on_noisy_data():
    rng = np.random.default_rng(1)
    X = rng.uniform(0, 1, size=(200, 4))
    y = X @ np.array([0.2, 0.1, 0.0, 0.05]) + rng.normal(0, 0.1, 200)
    rows = [{"markup": str(y[i]), "winner_pickup_eta": str(X[i, 0]), "beta": str(X[i, 1]),
             "base_price": str(X[i, 2]), "distance_km": str(X[i, 3])} for i in range(200)]
    A = np.column_stack([X, np.ones(200)])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    expected = 1 - np.sum((y - A @ coef) ** 2) / np.sum((y - y.mean()) ** 2)
    r = dg.r2_test(rows)
    assert r["r2"] == pytest.approx(expected)
    assert r["pass"] is True
    assert r["healthy"] is bool(0.3 <= expected <= 0.6)


def test_main_writes_json(tmp_path, monkeypatch):
    diag, e2, out = tmp_path / "diag.csv", tmp_path / "e2.csv", tmp_path / "sub" / "diagnostics.json"
    write_deals(diag, [row(m) for m in (1.0, 1.1, 1.2)])
    rng = np.random.default_rng(2)
    write_deals(e2, [row(rng.uniform(0.8, 1.5), eta=rng.uniform(1, 9), beta=rng.uniform(1, 1.4),
                         base=rng.uniform(100, 400), dist=rng.uniform(1, 30)) for _ in range(30)])
    monkeypatch.setattr("sys.argv", ["diagnostics.py", "--diag", str(diag), "--e2", str(e2), "--out", str(out)])
    dg.main()
    result = json.loads(out.read_text(encoding="utf-8"))
    assert set(result) == {"var_test", "r2_test"}
    assert set(result["var_test"]) == {"n", "std_markup", "pass"}
    assert set(result["r2_test"]) == {"n", "r2", "pass", "healthy"}
    assert result["var_test"]["n"] == 3
