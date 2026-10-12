"""Run from the repository root: python -m pytest scripts/paper"""
import csv
import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location("collect_numbers", Path(__file__).with_name("collect_numbers.py"))
cn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cn)


def write_csv(root, rel, header, rows):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def write_json(root, rel, obj):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def by_desc(items):
    return {d: (v, s) for d, v, s in items}


def test_values_sources_and_missing(tmp_path):
    write_json(tmp_path, "results/model_a/data_summary.json",
               {"routes_main": {"n": 400}, "cells": {"n": 82, "wet_hour_share_gt_0.1": 0.1101,
                                                     "period_utc": ["2022-06-01T00:00", "2025-11-30T23:00"]}})
    write_csv(tmp_path, "results/model_a/F1_curve.csv", ["subset", "method", "rho", "n", "mae", "ci_lo", "ci_hi"],
              [["MAIN", "B1", "0.25", 491, "0.149827", "0.114", "0.185"],
               ["MAIN", "B1", "0.5", 491, "0.101535", "0.078721", "0.122406"]])
    write_csv(tmp_path, "results/model_a/stats_tests.csv",
              ["a", "b", "rho", "n", "mean_diff", "ci_lo", "ci_hi", "median_diff", "p", "p_holm", "significant"],
              [["M2", "M1", "0.5", 491, "-0.029880", "-0.042115", "-0.016908", "-0.002", "0.000000", "0.000000", 1],
               ["M2", "M1", "0.75", 491, "-0.026191", "-0.037348", "-0.016051", "-0.002", "0.000001", "0.000757", 1]])

    items = cn.collect(str(tmp_path))
    got = by_desc(items)
    assert got["본 경로 수"] == ("400", "results/model_a/data_summary.json:routes_main.n")
    assert got["0.1mm 초과 강수 시간 비율"][0] == "0.1101"          # a JSON key holding a dot
    assert got["자료 기간 끝(UTC)"][0] == "2025-11-30T23:00"
    # CSV line numbers count the header as line 1.
    assert got["경로 평균 강수 MAE(mm/h) [95% CI], MAIN, B1, ρ = 0.5"] == (
        "0.1015 [0.0787, 0.1224]", "results/model_a/F1_curve.csv:3:mae,ci_lo,ci_hi")
    assert got["M2 대 M1 Holm 보정 p, ρ = 0.5"] == ("< 1e-6", "results/model_a/stats_tests.csv:2:p_holm")
    assert got["M2 대 M1 Holm 보정 p, ρ = 0.75"][0] == "7.57e-04"
    # Missing file, missing row, missing key: MISSING with the reason in the source column.
    assert got["보류 경로 수"][0] == "MISSING" and "키 없음" in got["보류 경로 수"][1]
    assert got["경로 평균 강수 MAE(mm/h) [95% CI], MAIN, M2, ρ = 0.5"][0] == "MISSING"
    assert got["T6 PR-AUC [95% CI], S4, model"] == ("MISSING", "results/collusion/T6_S4.csv")
    # Manual items do not depend on files.
    assert got["R13 동시 호가 20회(한 기사가 거래 60건에 8스레드로 호가)에서 매회 받아들여진 호가 수"][0] == "50"


def test_ids_do_not_shift_when_files_are_missing(tmp_path):
    empty = cn.collect(str(tmp_path / "nothing"))
    write_json(tmp_path, "results/model_a/summary.json", {"n_test_main": 491})
    some = cn.collect(str(tmp_path))
    assert [d for d, _, _ in empty] == [d for d, _, _ in some]
    assert len({d for d, _, _ in some}) == len(some)                 # every description is unique


def test_e7_max_and_numbers_md(tmp_path):
    write_csv(tmp_path, "results/sim/E7_collusion.csv",
              ["config", "strategy", "ring_share", "markup_median", "delta_vs_0", "ci_lo", "ci_hi", "honest_win_share"],
              [["C1", "S1", "0.5", "0.85", "0.008893", "0.003", "0.016", "0.95"],
               ["C3", "S1", "0.5", "0.895", "0.045", "0.038333", "0.05", "0.95"]])
    out = tmp_path / "paper" / "numbers.md"
    items = cn.main(["--root", str(tmp_path), "--output", str(out)])
    got = by_desc(items)
    assert got["E7 마크업 중앙값 증가의 최댓값(담합 0 대비) [95% CI]"] == (
        "0.045 [0.0383, 0.05] (C3, S1, 담합 비율 0.5)", "results/sim/E7_collusion.csv:3:delta_vs_0,ci_lo,ci_hi")
    text = out.read_text(encoding="utf-8")
    assert "| N01 | 본 경로 수 | MISSING |" in text
    assert f"| N{len(items):02d} |" in text
    n_missing = sum(v == "MISSING" for _, v, _ in items)
    assert f"MISSING {n_missing}개: N01" in text


def test_fmt():
    assert cn.fmt(400) == "400"
    assert cn.fmt("400") == "400"
    assert cn.fmt(0.743) == "0.743"
    assert cn.fmt("0.101535") == "0.1015"
    assert cn.fmt("0.000757") == "7.57e-04"
    assert cn.fmt("0.000000") == "0"
    assert cn.fmt("K2-log1p") == "K2-log1p"
