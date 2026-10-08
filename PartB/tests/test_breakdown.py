"""Card B7: breakdown tables from a fake per-sample CSV (the real test results are never recomputed)."""
import csv
import gzip

import pytest

from training import breakdown, final_eval


def row(sid, method, err, *, flags="MAIN|ALL", rho="0.5", stratum="short", U=3, season="sw_monsoon", week="2024-W23"):
    r = {c: "" for c in final_eval.PER_SAMPLE_COLUMNS}
    r.update(sample_id=sid, split="test", subset_flags=flags, method=method, rho=rho, k=1, stratum=stratum, U=U,
             season=season, iso_week=week, abs_err=f"{err:.6f}")
    return r


def write_per_sample(path, rows):
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=final_eval.PER_SAMPLE_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def results(tmp_path):
    rows = [
        # MAIN, rho 0.5: counted
        row(1, "B1", 0.30, stratum="short", U=3, season="sw_monsoon", week="2024-W23"),
        row(2, "B1", 0.10, stratum="short", U=5, season="ne_monsoon", week="2024-W43"),
        row(3, "B1", 0.20, stratum="long", U=9, season="dry", week="2025-W02"),
        row(1, "M2", 0.10, stratum="short", U=3, season="sw_monsoon", week="2024-W23"),
        row(3, "M2", 0.05, stratum="long", U=9, season="dry", week="2025-W02"),
        # not counted: other rho, k_abs row, not MAIN, R-T model row
        row(1, "B1", 9.0, rho="0.25"),
        row(1, "B1", 9.0, rho=""),
        row(4, "B1", 9.0, flags="ALL"),
        row(1, "M2", 9.0, flags="RT"),
    ]
    write_per_sample(tmp_path / breakdown.PER_SAMPLE, rows)
    breakdown.main(["--results-dir", str(tmp_path)])
    return tmp_path


def test_u_bins():
    assert [breakdown.u_bin(u) for u in (3, 4, 5, 6, 7, 8, 12)] == ["3", "4-5", "4-5", "6-7", "6-7", "8+", "8+"]


def test_tables_have_fixed_columns_and_only_main_rho_half(results):
    for name, (column, _, _) in breakdown.TABLES.items():
        table = read(results / name)
        assert list(table[0]) == [column, "method", "rho", "n", "mae", "ci_lo", "ci_hi"]
        assert {r["rho"] for r in table} == {"0.5"}
        assert all(float(r["mae"]) < 1 for r in table), "a 9.0 row leaked in"


def test_groups_methods_and_means(results):
    stratum = {(r["stratum"], r["method"]): r for r in read(results / "breakdown_stratum.csv")}
    assert list(stratum) == [("short", "B1"), ("short", "M2"), ("long", "B1"), ("long", "M2")]   # fixed order, empty skipped
    assert stratum[("short", "B1")]["n"] == "2"
    assert float(stratum[("short", "B1")]["mae"]) == pytest.approx(0.20)
    assert float(stratum[("short", "M2")]["mae"]) == pytest.approx(0.10)

    u = [(r["U_bin"], r["method"], r["n"]) for r in read(results / "breakdown_U.csv")]
    assert u == [("3", "B1", "1"), ("3", "M2", "1"), ("4-5", "B1", "1"), ("8+", "B1", "1"), ("8+", "M2", "1")]

    season = [(r["season"], r["method"]) for r in read(results / "breakdown_season.csv")]
    assert season == [("sw_monsoon", "B1"), ("sw_monsoon", "M2"), ("ne_monsoon", "B1"), ("dry", "B1"), ("dry", "M2")]


def test_ci_is_the_week_block_bootstrap(results):
    r = next(r for r in read(results / "breakdown_stratum.csv") if r["stratum"] == "short" and r["method"] == "B1")
    mae, lo, hi = breakdown.week_bootstrap_ci({"2024-W23": [0.30], "2024-W43": [0.10]}, B=2000, seed=42)
    assert (float(r["mae"]), float(r["ci_lo"]), float(r["ci_hi"])) == pytest.approx((mae, lo, hi), abs=1e-6)
