"""Run from the repository root: python -m pytest scripts/figures"""
import csv
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fake_results  # noqa: E402
import make_all  # noqa: E402
import style  # noqa: E402
import t1  # noqa: E402

FIGURES = ["F1_curve.png", "F1_kabs.png", "F2_uncertainty.png", "F3_markup.png", "F4_rounds.png", "F8_heatmap.png",
           "F9_collusion.png", "F10_offer.png"]
TABLES = ["T1", "T2", "T3", "T4", "T5", "T6"]


def run(tmp_path, name):
    results = fake_results.write_fake(tmp_path / "results")
    out = tmp_path / name
    written, skipped = make_all.make_all(str(results), str(out / "figures"), str(out / "tables"), log=lambda _: None)
    return results, out, written, skipped


def test_fake_results_make_every_file(tmp_path):
    _, out, written, skipped = run(tmp_path, "out")
    assert skipped == []
    for f in FIGURES:
        assert (out / "figures" / f).stat().st_size > 0
    for t in TABLES:
        assert (out / "tables" / f"{t}.md").exists()
        assert (out / "tables" / f"{t}_table.csv").exists()
    manifest = (out / "figures" / "MANIFEST.txt").read_text(encoding="utf-8").splitlines()
    assert len(manifest) == len(written)
    assert "figures/F1_curve.png" in {line.split("  ")[1] for line in manifest}


def test_png_bytes_are_the_same_on_a_second_run(tmp_path):
    _, a, _, _ = run(tmp_path, "a")
    _, b, _, _ = run(tmp_path, "b")
    for f in FIGURES:
        assert style.sha256(a / "figures" / f) == style.sha256(b / "figures" / f), f


def test_missing_inputs_are_skipped_and_listed(tmp_path):
    results = fake_results.write_fake(tmp_path / "results")
    os.remove(os.path.join(results, "sim", "E1_summary.csv"))
    os.remove(os.path.join(results, "collusion", "T6_S4.csv"))
    os.remove(os.path.join(results, "collusion", "T6_S5.csv"))
    lines = []
    _, skipped = make_all.make_all(results, str(tmp_path / "f"), str(tmp_path / "t"), log=lines.append)
    assert [s[0] for s in skipped] == ["F3", "F10", "T6"]
    assert lines[-1].startswith("skipped: F3 (sim")
    assert not (tmp_path / "f" / "F3_markup.png").exists()


def test_t1_marks_significant_m1_pairs_and_t3_keeps_its_inputs(tmp_path):
    results, out, _, _ = run(tmp_path, "out")
    t1 = (out / "tables" / "T1.md").read_text(encoding="utf-8")
    assert "| M1 (held-out routes) |" in t1 and "| B1 (held-out routes) |" in t1
    tests = style.read_csv(os.path.join(results, "model_a", "stats_tests.csv"))
    sig = [t for t in tests if "M1" in (t["a"], t["b"]) and float(t["p_holm"]) < 0.05]
    m1_row = next(line for line in t1.splitlines() if line.startswith("| M1 |"))
    assert ("†" in m1_row) == bool(sig)
    before = open(os.path.join(results, "tables", "T3_calls.csv"), encoding="utf-8").read()
    make_all.make_all(results, str(tmp_path / "f2"), os.path.join(results, "tables"), log=lambda _: None)
    assert open(os.path.join(results, "tables", "T3_calls.csv"), encoding="utf-8").read() == before


def test_t1_footnote_with_a_known_significant_pair(tmp_path):
    results = fake_results.write_fake(tmp_path / "results")
    path = os.path.join(results, "model_a", "stats_tests.csv")
    rows = style.read_csv(path)
    for r in rows:
        r["p_holm"] = "0.01" if (r["a"], r["b"], r["rho"]) == ("M2", "M1", "0.500000") else "0.5"
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    t1.make(results, str(tmp_path / "t"))
    md = (tmp_path / "t" / "T1.md").read_text(encoding="utf-8")
    m1_row = next(line for line in md.splitlines() if line.startswith("| M1 |"))
    assert m1_row.split(" | ")[2].endswith("]†")          # only the k/U = 0.50 cell
    assert "M2 − M1 at k/U = 0.50" in md


def test_fake_results_refuse_the_real_results_dir():
    with pytest.raises(ValueError):
        fake_results.write_fake(os.path.join(fake_results.REAL_RESULTS, "tmp"))
