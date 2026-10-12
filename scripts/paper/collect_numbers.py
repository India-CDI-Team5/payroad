"""Every number the paper may cite, read from results/ into paper/numbers.md (card P1).

Run from the repository root:
  python scripts/paper/collect_numbers.py

Each line of numbers.md is "| N01 | 설명 | 값 | 출처 |". The source is file:line:column for a CSV (line 1 is the
header), file:key.path for a JSON, and "수동: …" for the few values that live in no result file. A value whose file
is missing (or whose row is not there) is "MISSING"; the item keeps its number so the IDs do not shift.
The paper cites only these values, with [[N번호]] markers (paper writing rule 2).
"""
import argparse
import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
OUTPUT = os.path.join(ROOT, "paper", "numbers.md")

METHODS = ["B0", "B1", "B1-L", "B2", "B2-L", "M1", "M2"]
RHOS = ["0.25", "0.5", "0.75"]
CONFIGS = ["C1", "C2", "C3", "C4"]
PAIRS = [("B2", "B1", "격자 셀 중복 제거 효과"), ("M1", "B2-L", "순수 GP 보간 효과"),
         ("M1", "B1", "현행 대비 GP 보간"), ("M2", "M1", "불확실성 기반 추가 배치 효과")]

# Values that live in no result file (card P1). Each names where it was read.
MANUAL = [
    ("동시 수락 시나리오 A(기사 오퍼 수락 대 승객 지목 수락) 200회의 이중 체결 수", "0",
     "수동: PartA DealConcurrencyTest S_A = 200, ./gradlew test 통과 2026-10-12"),
    ("동시 수락 시나리오 B(한 기사가 두 거래에서 동시 체결) 200회의 이중 체결 수", "0",
     "수동: PartA DealConcurrencyTest S_B = 200, ./gradlew test 통과 2026-10-12"),
    ("R13 동시 호가 20회(한 기사가 거래 60건에 8스레드로 호가)에서 매회 받아들여진 호가 수", "50",
     "수동: PartA DealConcurrencyTest S_C = 20, ./gradlew test 통과 2026-10-12"),
    ("R10 정리 루프 예비 측정, 활성 호가 N = 1 소요 시간(ms)", "7.50", "수동: docs/api-spec.md v1.3 R13 표"),
    ("R10 정리 루프 예비 측정, N = 50(R13 상한) 소요 시간(ms), N = 1 대비 약 +0.03ms", "7.53",
     "수동: docs/api-spec.md v1.3 R13 표"),
    ("R10 정리 루프 예비 측정, N = 1,000,000 소요 시간(ms)", "1044.62", "수동: docs/api-spec.md v1.3 R13 표"),
]


class Missing(Exception):
    """A source file or row is not there."""


class Sources:
    def __init__(self, root):
        self.root = root
        self._csv = {}

    def _path(self, rel):
        path = os.path.join(self.root, rel)
        if not os.path.exists(path):
            raise Missing(rel)
        return path

    def rows(self, rel):
        if rel not in self._csv:
            with open(self._path(rel), newline="", encoding="utf-8") as f:
                self._csv[rel] = list(csv.DictReader(f))
        return self._csv[rel]

    def row(self, rel, **where):
        """(line number, row) of the first row matching every column = value (numbers compared as floats)."""
        for i, r in enumerate(self.rows(rel)):
            if all(_same(r.get(k), v) for k, v in where.items()):
                return i + 2, r
        raise Missing(f"{rel} ({', '.join(f'{k}={v}' for k, v in where.items())} 행 없음)")

    def cell(self, rel, col, **where):
        line, r = self.row(rel, **where)
        if r.get(col) in (None, ""):
            raise Missing(f"{rel}:{line}:{col} (빈칸)")
        return r[col], f"{rel}:{line}:{col}"

    def json(self, rel, key):
        with open(self._path(rel), encoding="utf-8") as f:
            v = json.load(f)
        parts = key.split(".")
        while parts:  # a key may itself hold dots (wet_hour_share_gt_0.1): take the longest match
            for n in range(len(parts), 0, -1):
                k = ".".join(parts[:n])
                if isinstance(v, dict) and k in v:
                    v, parts = v[k], parts[n:]
                    break
            else:
                raise Missing(f"{rel}:{key} (키 없음)")
        return v, f"{rel}:{key}"


def _missing(why):
    raise Missing(why)


def _same(a, b):
    if a is None:
        return False
    try:
        return float(a) == float(b)
    except ValueError:
        return a == str(b)


def fmt(v):
    """Integers as is; other numbers to 4 decimals without trailing zeros (below 0.001: 3 significant digits)."""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    s = str(v)
    try:
        f = float(s)
    except ValueError:
        return s
    if isinstance(v, str) and "." not in s and "e" not in s.lower():
        return s
    if f != 0 and abs(f) < 0.001:
        return f"{f:.2e}"
    return f"{f:.4f}".rstrip("0").rstrip(".")


def collect(root):
    """[(description, value, source)] in the order of numbers.md."""
    src = Sources(root)
    items = []

    def add(desc, get):
        try:
            value, where = get()
            items.append((desc, fmt(value), where))
        except Missing as e:
            items.append((desc, "MISSING", str(e)))

    def with_ci(rel, val_col, lo_col, hi_col, **where):
        line, r = src.row(rel, **where)
        if r.get(val_col) in (None, ""):
            raise Missing(f"{rel}:{line}:{val_col} (빈칸)")
        return (f"{fmt(r[val_col])} [{fmt(r[lo_col])}, {fmt(r[hi_col])}]",
                f"{rel}:{line}:{val_col},{lo_col},{hi_col}")

    def p_value(rel, col, **where):
        """stats_tests.csv keeps 6 decimals, so a printed 0 means below 0.0000005."""
        v, at = src.cell(rel, col, **where)
        return ("< 1e-6" if float(v) == 0 else v), at

    ds, ma = "results/model_a/data_summary.json", "results/model_a"
    sm, gp = f"{ma}/summary.json", "PartB/models/gp_interpolator.json"

    # Data (Ⅲ-1)
    add("본 경로 수", lambda: src.json(ds, "routes_main.n"))
    add("보류 경로 수", lambda: src.json(ds, "routes_holdout.n"))
    add("본 경로 거리 중앙값(km)", lambda: src.json(ds, "routes_main.distance_km.median"))
    add("기상 격자 셀 수", lambda: src.json(ds, "cells.n"))
    add("셀별 시간 수", lambda: src.json(ds, "cells.hours"))
    add("자료 기간 시작(UTC)", lambda: (src.json(ds, "cells.period_utc")[0][0], f"{ds}:cells.period_utc[0]"))
    add("자료 기간 끝(UTC)", lambda: (src.json(ds, "cells.period_utc")[0][1], f"{ds}:cells.period_utc[1]"))
    add("0.1mm 초과 강수 시간 비율", lambda: src.json(ds, "cells.wet_hour_share_gt_0.1"))
    for split, name in [("train", "학습"), ("val", "검증"), ("test", "테스트"), ("test_holdout", "보류 테스트")]:
        add(f"표본 수, {name} 분할", lambda s=split: src.json(ds, f"samples.by_split.{s}"))
    for split, name in [("train", "학습"), ("val", "검증"), ("test", "테스트")]:
        add(f"ISO 주 수, {name} 분할", lambda s=split: src.json(ds, f"samples.iso_weeks_by_split.{s}"))
    add("U ≥ 3 경로 비율, 본 경로", lambda: src.json(ds, "routes_main.share_U_ge_3"))
    add("U ≥ 3 경로 비율, 보류 경로", lambda: src.json(ds, "routes_holdout.share_U_ge_3"))
    add("우천 표본 비율, 테스트 분할", lambda: src.json(ds, "samples.wet_share_by_split.test"))
    add("MAIN(테스트·U ≥ 3·우천) 표본 수", lambda: src.json(sm, "n_test_main"))
    add("HOLDOUT(보류·U ≥ 3·우천) 표본 수", lambda: src.json(sm, "n_holdout_main"))
    add("MAIN의 ISO 주 수", lambda: src.json(sm, "n_weeks_main"))

    # GP setting (Ⅱ-3, Ⅱ-4)
    add("선택된 GP 설정(커널-변환)", lambda: src.json(gp, "config"))
    add("선택된 커널", lambda: src.json(gp, "kernel"))
    add("거리 축 길이 척도 ℓ_s(km)", lambda: src.json(gp, "params.ls_s"))
    add("신호 표준편차 σ_f", lambda: src.json(gp, "params.sigma_f"))
    add("잡음 표준편차 σ_n", lambda: src.json(gp, "params.sigma_n"))
    add("분산 보정 계수 κ", lambda: src.json(gp, "kappa"))
    add("초매개변수 학습 표본 수", lambda: src.json(gp, "n_train_samples"))
    add("강수 할증 계수 c_β", lambda: src.json("config/pricing-constants.json", "betaCoef"))

    # Accuracy (Ⅲ-2): MAIN, every method and budget, with the week-block bootstrap CI
    f1 = f"{ma}/F1_curve.csv"
    for m in METHODS:
        for rho in RHOS:
            add(f"경로 평균 강수 MAE(mm/h) [95% CI], MAIN, {m}, ρ = {rho}",
                lambda m=m, rho=rho: with_ci(f1, "mae", "ci_lo", "ci_hi", subset="MAIN", method=m, rho=rho))
    add("B1 셀 중복 조회율, ρ = 1.0", lambda: src.cell(f"{ma}/B1_duplicate.csv", "mean_duplicate_rate", rho="1.0"))
    t1 = f"{ma}/T1_table.csv"
    for m in ["B1-L", "B2", "B2-L", "M1", "M2"]:
        add(f"호출 절감율(같은 MAE, B1 대비), {m}", lambda m=m: src.cell(t1, "saving_vs_B1", subset="MAIN", method=m))
    st = f"{ma}/stats_tests.csv"
    for a, b, what in PAIRS:
        for rho in RHOS:
            add(f"{a} − {b} 절대 오차 평균 차 [95% CI], ρ = {rho} ({what})",
                lambda a=a, b=b, rho=rho: with_ci(st, "mean_diff", "ci_lo", "ci_hi", a=a, b=b, rho=rho))
            add(f"{a} 대 {b} Holm 보정 p, ρ = {rho}", lambda a=a, b=b, rho=rho: p_value(st, "p_holm", a=a, b=b, rho=rho))
    for subset, name in [("HOLDOUT", "보류 경로"), ("RT", "시간 분리 R-T")]:
        for m in ["B1", "M1", "M2"]:
            add(f"MAE(mm/h) [95% CI], {name}, {m}, ρ = 0.5",
                lambda subset=subset, m=m: with_ci(f1, "mae", "ci_lo", "ci_hi", subset=subset, method=m, rho="0.5"))

    # Uncertainty (Ⅲ-3)
    cov, spm = f"{ma}/F2_coverage.csv", f"{ma}/F2_spearman.csv"
    for m in ["M1", "M2"]:
        for rho in RHOS:
            add(f"지점 95% 포함률, {m}, ρ = {rho}", lambda m=m, rho=rho: src.cell(cov, "cov_points", method=m, rho=rho))
            add(f"경로 평균 95% 포함률, {m}, ρ = {rho}", lambda m=m, rho=rho: src.cell(cov, "cov_mean", method=m, rho=rho))
            add(f"불확실성 s와 오차의 Spearman ρ, {m}, 예산 비율 {rho}",
                lambda m=m, rho=rho: src.cell(spm, "spearman", method=m, rho=rho))
    bc = f"{ma}/F2_beta_compare.csv"
    add("할증 비교 표본 수(M1, ρ = 0.5)", lambda: src.cell(bc, "n", rule="beta_r"))
    for rule, name in [("beta_r", "β(r)"), ("beta_rs", "β(r, s)")]:
        add(f"오할증률, {name}", lambda rule=rule: src.cell(bc, "over_rate", rule=rule))
        add(f"미할증률, {name}", lambda rule=rule: src.cell(bc, "under_rate", rule=rule))
        add(f"할증 일치율, {name}", lambda rule=rule: src.cell(bc, "agree", rule=rule))
    for coef in ["0.1", "0.15", "0.2", "0.3"]:
        add(f"c_β = {coef}에서 M2의 할증 일치율 순위(7개 방법 중)",
            lambda coef=coef: src.cell(f"{ma}/T2_beta_sensitivity.csv", "rank", coef=coef, method="M2"))
    fe = f"{ma}/forecast_error.csv"
    add("1일 전 예보 검증 표본 수", lambda: src.cell(fe, "n"))
    add("1일 전 예보의 경로 평균 MAE(mm/h)", lambda: src.cell(fe, "mae_fc"))
    add("1일 전 예보의 할증 판단 반전율", lambda: src.cell(fe, "flip_rate"))
    add("같은 표본에서 M1 MAE(mm/h), ρ = 0.5", lambda: src.cell(fe, "m1_mae_rho50"))

    # Serving calls (프로시딩 3.3)
    t3 = "results/tables/T3_calls.csv"
    for m, name in [("current_cells", "현행 지점에서 같은 셀 중복 제거"), ("all_cells_U", "경로의 셀 전부 조회"),
                    ("proposed_M2", "제안(M2, 예산 비율 0.5)")]:
        add(f"T3 호출 수 절감율(현행 대비), {name}", lambda m=m: src.cell(t3, "saving_vs_current", method=m))

    # Mechanism (Ⅲ-4)
    dg = "results/sim/diagnostics.json"
    add("봇 자가 진단 R²(마크업 회귀)", lambda: src.json(dg, "r2_test.r2"))
    add("봇 자가 진단 마크업 표준편차", lambda: src.json(dg, "var_test.std_markup"))
    e1 = "results/sim/E1_trend.csv"
    for c in CONFIGS:
        add(f"E1 기사 수와 마크업 중앙값의 Spearman ρ, {c}", lambda c=c: src.cell(e1, "spearman_n_markup", config=c))
        add(f"E1 마크업 중앙값 차(n = 1 − n = 10) [95% CI], {c}",
            lambda c=c: with_ci(e1, "diff_n1_minus_n10", "ci_lo", "ci_hi", config=c))
        add(f"E1 단조 감소 판정(1 = 통과), {c}", lambda c=c: src.cell(e1, "monotone_decrease", config=c))
    e2 = "results/sim/E2_end.csv"
    for c in CONFIGS:
        add(f"E2 체결률, {c}", lambda c=c: src.cell(e2, "matched", config=c))
        add(f"E2 라운드 상한 종료 비율, {c}", lambda c=c: src.cell(e2, "round_limit", config=c))
    e3 = "results/sim/E3_fixed.csv"
    for c in CONFIGS:
        add(f"E3 흥정 체결률 [95% CI], {c}",
            lambda c=c: with_ci(e3, "match_rate", "ci_lo", "ci_hi", config=c, mode="bargain"))
        add(f"E3 고정가 체결률, {c}", lambda c=c: src.cell(e3, "match_rate", config=c, mode="fixed"))
        add(f"E3 흥정 체결까지 시간 중앙값(초), {c}",
            lambda c=c: src.cell(e3, "time_to_match_median", config=c, mode="bargain"))
    e7 = "results/sim/E7_collusion.csv"

    def e7_max():
        rows = src.rows(e7)
        if not rows:
            raise Missing(f"{e7} (행 없음)")
        i, r = max(enumerate(rows), key=lambda x: float(x[1]["delta_vs_0"]))
        return (f"{fmt(r['delta_vs_0'])} [{fmt(r['ci_lo'])}, {fmt(r['ci_hi'])}] "
                f"({r['config']}, {r['strategy']}, 담합 비율 {fmt(r['ring_share'])})",
                f"{e7}:{i + 2}:delta_vs_0,ci_lo,ci_hi")
    add("E7 마크업 중앙값 증가의 최댓값(담합 0 대비) [95% CI]", e7_max)

    # Collusion (Ⅲ-4)
    for s in ["S4", "S5"]:
        t6 = f"results/collusion/T6_{s}.csv"
        for m in ["model", "B-price", "B-rule"]:
            add(f"T6 PR-AUC [95% CI], {s}, {m}", lambda t6=t6, m=m: with_ci(t6, "pr_auc", "ci_lo", "ci_hi", method=m))
        add(f"T6 고정 임계 재현율, {s}, model", lambda t6=t6: src.cell(t6, "recall_at_thr", method="model"))
        add(f"T6 고정 임계 FPR, {s}, model", lambda t6=t6: src.cell(t6, "fpr_at_thr", method="model"))

    # Pilot (E3, skipped on 2026-10-12: stays MISSING)
    pl = "results/pilot/pilot_summary.csv"
    add("파일럿 체결 수 n", lambda: src.cell(pl, "n_matched"))
    add("파일럿 최저가 선택 비율", lambda: src.cell(pl, "rank1_share"))

    # Manual
    for desc, value, where in MANUAL:
        add(desc, lambda value=value, where=where: (value, where))
    add("실험 러너 에피소드당 실행 시간(ms), C2 보고서", lambda: _missing("수동: C2 보고서가 저장소에 없음"))
    return items


def write(items, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    missing = [(i, d) for i, (d, v, _) in enumerate(items, 1) if v == "MISSING"]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# 논문 숫자 (카드 P1, scripts/paper/collect_numbers.py가 생성)\n\n")
        f.write("손으로 고치지 않는다. results/가 바뀌면 스크립트를 다시 실행한다. "
                "본문에는 값 뒤에 [[N번호]]를 붙인다.\n\n")
        f.write("| N | 설명 | 값 | 출처 |\n|---|---|---|---|\n")
        for i, (desc, value, where) in enumerate(items, 1):
            f.write(f"| N{i:02d} | {desc} | {value} | {where} |\n")
        f.write(f"\nMISSING {len(missing)}개" + (": " + ", ".join(f"N{i:02d}" for i, _ in missing) if missing else "") + "\n")
    return missing


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--root", default=ROOT, help="repository root holding results/, PartB/ and config/")
    p.add_argument("--output", default=OUTPUT)
    a = p.parse_args(argv)
    items = collect(a.root)
    missing = write(items, a.output)
    print(f"{a.output}: {len(items)} items, MISSING {len(missing)}")
    for i, d in missing:
        print(f"  N{i:02d} {d}")
    return items


if __name__ == "__main__":
    main()
