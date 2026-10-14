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

    # Added for card P3 (appended so that earlier IDs do not shift)
    add("E7 마크업 중앙값 증가(담합 0 대비) [95% CI], C3, S2, 담합 비율 0.5",
        lambda: with_ci(e7, "delta_vs_0", "ci_lo", "ci_hi", config="C3", strategy="S2", ring_share="0.5"))

    def e7_max_outside(config):
        rows = [(i, r) for i, r in enumerate(src.rows(e7)) if r["config"] != config]
        if not rows:
            raise Missing(f"{e7} (행 없음)")
        i, r = max(rows, key=lambda x: float(x[1]["delta_vs_0"]))
        return (f"{fmt(r['delta_vs_0'])} ({r['config']}, {r['strategy']}, 담합 비율 {fmt(r['ring_share'])})",
                f"{e7}:{i + 2}:delta_vs_0")
    add("E7 마크업 중앙값 증가의 최댓값, C3 제외", lambda: e7_max_outside("C3"))

    def e7_s4_honest(pick):
        rows = [(i, r) for i, r in enumerate(src.rows(e7)) if r["strategy"] == "S4" and _same(r["ring_share"], 0.5)]
        if not rows:
            raise Missing(f"{e7} (S4 비율 0.5 행 없음)")
        i, r = pick(rows, key=lambda x: float(x[1]["honest_win_share"]))
        return r["honest_win_share"], f"{e7}:{i + 2}:honest_win_share ({r['config']})"
    add("E7 S4 담합 비율 0.5에서 정직한 기사의 체결 점유율, 4구성 중 최솟값", lambda: e7_s4_honest(min))
    add("E7 S4 담합 비율 0.5에서 정직한 기사의 체결 점유율, 4구성 중 최댓값", lambda: e7_s4_honest(max))

    # Added for card P5 (appended)
    def e2_ttl_max():
        rows = list(enumerate(src.rows(e2)))
        if not rows:
            raise Missing(f"{e2} (행 없음)")
        i, r = max(rows, key=lambda x: float(x[1]["ttl"]))
        return r["ttl"], f"{e2}:{i + 2}:ttl ({r['config']})"
    add("E2 TTL(180초) 종료 비율, 4구성 중 최댓값", e2_ttl_max)
    f9 = "results/collusion/F9_S4.csv"
    add("F9 S4 PR-AUC [95% CI], model, 담합 비율 0.1",
        lambda: with_ci(f9, "pr_auc", "ci_lo", "ci_hi", method="model", ring_share="0.1"))
    add("F9 S4 PR-AUC, B-price, 담합 비율 0.1", lambda: src.cell(f9, "pr_auc", method="B-price", ring_share="0.1"))

    def f9_wins():
        rows = src.rows(f9)
        model = {float(r["ring_share"]): float(r["pr_auc"]) for r in rows if r["method"] == "model"}
        price = {float(r["ring_share"]): float(r["pr_auc"]) for r in rows if r["method"] == "B-price"}
        if not model:
            raise Missing(f"{f9} (행 없음)")
        wins = sum(model[k] > price.get(k, 1.0) for k in model)
        return f"{wins}/{len(model)}", f"{f9}:pr_auc (model 대 B-price, 비율별)"
    add("F9 S4 모델 PR-AUC가 B-price보다 높은 담합 비율 수 / 전체 비율 수", f9_wins)
    add("T3 경로당 평균 호출 수, 현행 지점 조회", lambda: src.cell(t3, "mean_calls", method="current_points"))
    add("T3 경로당 평균 호출 수, 제안(M2, 예산 비율 0.5)", lambda: src.cell(t3, "mean_calls", method="proposed_M2"))
    add("T3 비교 경로 수", lambda: src.cell(t3, "routes", method="current_points"))
    add("E3 고정가 체결까지 시간 중앙값(초), C1", lambda: src.cell(e3, "time_to_match_median", config="C1", mode="fixed"))

    # Added for card P7 (mock review answers, appended)
    for m in ["B1", "M2"]:
        add(f"MAE(mm/h) [95% CI], ALL(테스트·U ≥ 3·맑은 표본 포함), {m}, ρ = 0.5",
            lambda m=m: with_ci(t1, "mae_rho50", "ci50_lo", "ci50_hi", subset="ALL", method=m))
    add("ALL 부분집합 표본 수", lambda: src.cell(t1, "n", subset="ALL", method="M1"))

    def main_truth(stat):
        import gzip
        import statistics
        rel = f"{ma}/test_per_sample.csv.gz"
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            raise Missing(rel)
        with gzip.open(path, "rt", newline="", encoding="utf-8") as f:
            m = [float(r["m_true"]) for r in csv.DictReader(f)
                 if r["method"] == "M1" and _same(r["rho"], 0.5) and "MAIN" in r["subset_flags"].split("|")]
        if not m:
            raise Missing(f"{rel} (MAIN 행 없음)")
        return (statistics.median(m) if stat == "median" else statistics.fmean(m)), f"{rel}:m_true (MAIN, n = {len(m)})"
    add("MAIN 정답 경로 평균 강수 m의 중앙값(mm/h)", lambda: main_truth("median"))
    add("MAIN 정답 경로 평균 강수 m의 평균(mm/h)", lambda: main_truth("mean"))
    add("담합 탐지 동결 모델 설정", lambda: src.json("collusion/configs/collusion_frozen.json", "selected"))

    # Post-hoc additions (paper-revision-v1 X5, 2026-10-14, appended). Tests were opened before these analyses.
    ph, phs = "results/posthoc/model_a", "results/posthoc/sim"
    prof, pmae = f"{ph}/placement_profile.csv", f"{ph}/placement_mae.csv"
    psav, ptest = f"{ph}/placement_saving.csv", f"{ph}/placement_tests.csv"
    offer, paths, rank = f"{phs}/E1_offer_base.csv", f"{phs}/E1_offer_paths.csv", f"{phs}/E5_rank_premium.csv"
    rules = ["H-C", "H-P", "H-R", "H-N", "H-D", "H-S"]

    def profile_share(prefix):
        line, r = src.row(prof, key="main_n")
        n = float(r["value"])
        v, at = src.cell(prof, "value", key=prefix)
        return float(v) / n, f"{at} / {prof}:{line}:value(main_n)"

    add("사후: MAIN U 평균", lambda: src.cell(prof, "value", key="main_U_mean"))
    add("사후: MAIN U 중앙값", lambda: src.cell(prof, "value", key="main_U_median"))
    add("사후: MAIN 예산 비율 0.5에서 k = 2인 표본 비율", lambda: profile_share("main_k_count_rho0.5_2"))
    add("사후: MAIN 예산 비율 0.5에서 M2가 분산으로 고른 셀이 1개인 표본 비율",
        lambda: profile_share("main_var_picks_count_rho0.5_1"))
    add("사후: MAIN 첫·끝 셀의 평균 지점 수", lambda: src.cell(prof, "value", key="endcell_points_mean"))
    add("사후: MAIN 안쪽 셀의 평균 지점 수", lambda: src.cell(prof, "value", key="innercell_points_mean"))
    add("사후: B1이 k/U = 1.0에서 놓친 셀 비율(표본 평균, 셀 중복률과 같음)",
        lambda: src.cell(prof, "value", key="b1_rho1_missed_cell_share_mean"))
    for m in rules:
        add(f"사후: MAIN MAE(mm/h) [95% CI], {m}, 예산 비율 0.5",
            lambda m=m: with_ci(pmae, "mae", "ci_lo", "ci_hi", subset="MAIN", method=m, rho="0.5"))
    for m in rules:
        def saving(m=m):
            line, r = src.row(psav, method=m)
            if r["saving_vs_B1"] == "":
                return "미도달", f"{psav}:{line}:saving_vs_B1"
            return r["saving_vs_B1"], f"{psav}:{line}:saving_vs_B1"
        add(f"사후: 동일 정확도 호출 절감률(B1 대비), {m}", saving)
    for m in rules:
        add(f"사후: M2 − {m} 절대 오차 평균 차 [95% CI], 예산 비율 0.5",
            lambda m=m: with_ci(ptest, "mean_diff", "ci_lo", "ci_hi", a="M2", b=m, rho="0.5"))
        add(f"사후: M2 대 {m} Holm 보정 p(사후 24검정), 예산 비율 0.5",
            lambda m=m: p_value(ptest, "p_holm", a="M2", b=m, rho="0.5"))
    for rho in RHOS:
        add(f"사후: M2 − B1 절대 오차 평균 차 [95% CI], 예산 비율 {rho}",
            lambda rho=rho: with_ci(ptest, "mean_diff", "ci_lo", "ci_hi", a="M2", b="B1", rho=rho))
        add(f"사후: M2 대 B1 Holm 보정 p(사후 24검정), 예산 비율 {rho}",
            lambda rho=rho: p_value(ptest, "p_holm", a="M2", b="B1", rho=rho))
    add("사후: H-C − M1 절대 오차 평균 차 [95% CI], 예산 비율 0.5",
        lambda: with_ci(ptest, "mean_diff", "ci_lo", "ci_hi", a="H-C", b="M1", rho="0.5"))
    add("사후: H-C 대 M1 Holm 보정 p(사후 24검정), 예산 비율 0.5",
        lambda: p_value(ptest, "p_holm", a="H-C", b="M1", rho="0.5"))
    for m in rules:
        add(f"사후: 예산 비율 0.5에서 {m}가 M2와 같은 셀 집합을 고른 비율",
            lambda m=m: src.cell(prof, "value", key=f"same_as_m2_share_rho0.5_{m}"))

    def offer_passes():
        rows = [r for r in src.rows(offer) if r["offer_base"] in ("0.90", "1.00")]
        if not rows:
            raise Missing(f"{offer} (0.90·1.00 행 없음)")
        return f"{sum(r['monotone_decrease'] == '1' for r in rows)}/{len(rows)}", f"{offer}:monotone_decrease (0.90·1.00)"
    add("사후: 첫 오퍼 0.90·1.00에서 E1 단조 감소 판정 통과 수 / 조건 수", offer_passes)
    add("사후: 첫 오퍼 0.90, C1, 기사 수와 마크업 중앙값의 Spearman ρ",
        lambda: src.cell(offer, "spearman_n_markup", offer_base="0.90", config="C1"))
    add("사후: 첫 오퍼 0.90, C1, 마크업 중앙값 차(n = 1 − n = 10) [95% CI]",
        lambda: with_ci(offer, "diff_n1_minus_n10", "ci_lo", "ci_hi", offer_base="0.90", config="C1"))
    for level in ["0.90", "1.00"]:
        add(f"사후: 첫 오퍼 {level}, C1, 마크업 중앙값, n = 1",
            lambda level=level: src.cell(offer, "markup_n1", offer_base=level, config="C1"))
        add(f"사후: 첫 오퍼 {level}, C1, 마크업 중앙값, n = 10",
            lambda level=level: src.cell(offer, "markup_n10", offer_base=level, config="C1"))
        add(f"사후: 첫 오퍼 {level}, C1, 체결률, n = 10",
            lambda level=level: src.cell(offer, "match_n10", offer_base=level, config="C1"))

    def took_offer(stat):
        rows = [(i, r) for i, r in enumerate(src.rows(paths)) if r["offer_base"] == "1.00"]
        if not rows:
            raise Missing(f"{paths} (1.00 행 없음)")
        i, r = (min if stat == "min" else max)(rows, key=lambda x: float(x[1]["took_offer_share"]))
        return r["took_offer_share"], f"{paths}:{i + 2}:took_offer_share ({r['config']}, n = {r['n']})"
    add("사후: 첫 오퍼 1.00에서 기사가 승객 오퍼를 수락해 끝난 거래 비율, 구성·n 중 최솟값", lambda: took_offer("min"))
    add("사후: 첫 오퍼 1.00에서 기사가 승객 오퍼를 수락해 끝난 거래 비율, 구성·n 중 최댓값", lambda: took_offer("max"))
    add("사후: E5, C1, τ = 0.05, 승객이 고른 체결 중 최저가가 아닌 호가 비율",
        lambda: src.cell(rank, "share_nonlowest", config="C1", tau="0.05"))
    add("사후: E5, C1, τ = 0.05, 최저가가 아닌 호가를 고를 때 더 낸 가격(기준가 대비)",
        lambda: src.cell(rank, "extra_price_ratio_mean", config="C1", tau="0.05"))
    add("사후: E5, C1, τ = 0.05, 최저가가 아닌 호가를 고를 때 줄어든 픽업 시간(분)",
        lambda: src.cell(rank, "eta_saved_min_mean", config="C1", tau="0.05"))
    add("사후: B1이 k/U = 1.0에서 얻는 MAE(동일 정확도 호출 절감률의 목표, mm/h)",
        lambda: src.cell(psav, "target_mae", method="B1"))

    def per_10k(method):
        v, at = src.cell(t3, "mean_calls", method=method)
        return int(round(float(v) * 10000)), f"{at} × 10,000"
    add("사후: 경로 1만 건당 예보 호출 수, 현행 지점 조회", lambda: per_10k("current_points"))
    add("사후: 경로 1만 건당 예보 호출 수, 제안(M2, 예산 비율 0.5)", lambda: per_10k("proposed_M2"))

    # Second feedback round (paper-revision-v1 X14, 2026-10-15, appended): held-out check of the post-hoc rule and
    # the grid points behind the call savings.
    add("사후: HOLDOUT MAE(mm/h) [95% CI], H-P, 예산 비율 0.5",
        lambda: with_ci(pmae, "mae", "ci_lo", "ci_hi", subset="HOLDOUT", method="H-P", rho="0.5"))
    for m in ["B1", "M2", "H-P"]:
        add(f"사후: B1의 k/U = 1.0 MAE에 처음 도달한 예산 비율(0.05 격자), {m}",
            lambda m=m: src.cell(psav, "first_rho", method=m))
    for m in ["M1", "M2"]:
        add(f"최대 강수 셀 적중률(k/U = 0.5), MAIN, {m}",
            lambda m=m: src.cell(f"{ma}/T1_table.csv", "max_hit_rho50", subset="MAIN", method=m))

    # Third feedback round (paper-revision-v1 X15, 2026-10-15, appended): previous system's error, MAE by k,
    # surcharge decision beyond agreement.
    prev, kbin, kap = f"{ph}/previous_mae.csv", f"{ph}/kbin_mae.csv", f"{ph}/surcharge_kappa.csv"
    for sub in ["MAIN", "HOLDOUT"]:
        add(f"사후: 이전 방식(거리별 지점 4·6·9·12개, 최근접 값) MAE(mm/h) [95% CI], {sub}",
            lambda sub=sub: with_ci(prev, "mae", "ci_lo", "ci_hi", subset=sub))
    add("사후: 이전 방식의 경로당 평균 지점 수(= 호출 수), HOLDOUT", lambda: src.cell(prev, "mean_points", subset="HOLDOUT"))
    add("사후: 이전 방식의 경로당 평균 고유 셀 수, HOLDOUT", lambda: src.cell(prev, "mean_cells", subset="HOLDOUT"))
    for sub, kb, m in [("MAIN", "2", "M1"), ("MAIN", "2", "M2"), ("MAIN", "2", "H-P"), ("MAIN", ">=3", "M1"),
                       ("MAIN", ">=3", "M2"), ("MAIN", ">=3", "H-P"), ("HOLDOUT", ">=3", "M2"), ("HOLDOUT", ">=3", "H-P")]:
        add(f"사후: {sub} MAE(mm/h), 예산 비율 0.5, k {kb}, {m}",
            lambda sub=sub, kb=kb, m=m: src.cell(kbin, "mae", subset=sub, rho="0.5", k_bin=kb, method=m))
    add("사후: MAIN 예산 비율 0.5에서 참 할증(β(r, 0) > 1.2) 표본 비율", lambda: src.cell(kap, "base_rate", method="M2"))
    for m in ["B1", "M2"]:
        add(f"사후: MAIN 예산 비율 0.5 할증 판단의 Cohen κ, {m}", lambda m=m: src.cell(kap, "kappa", method=m))
    add("사후: MAIN 예산 비율 0.5 할증 판단의 재현율, M2", lambda: src.cell(kap, "recall", method="M2"))

    # Fourth feedback round (paper-revision-v1 X16, 2026-10-15, appended).
    pcell, kaprs = f"{ph}/previous_cells_mae.csv", f"{ph}/surcharge_kappa_rs.csv"
    add("사후: 이전 지점의 고유 셀만 조회(중복 셀 제거) MAE(mm/h) [95% CI], HOLDOUT",
        lambda: with_ci(pcell, "mae", "ci_lo", "ci_hi", subset="HOLDOUT"))
    add("사후: 이전 지점의 고유 셀만 조회할 때 경로당 평균 호출 수, HOLDOUT", lambda: src.cell(pcell, "mean_cells", subset="HOLDOUT"))
    add("사후: MAIN 예산 비율 0.5 할증 판단 β(r, 0)의 Cohen κ, M1", lambda: src.cell(kap, "kappa", method="M1"))
    for m in ["M1", "M2"]:
        add(f"사후: MAIN 예산 비율 0.5 할증 판단 β(r, s)의 Cohen κ, {m}", lambda m=m: src.cell(kaprs, "kappa", method=m))
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
