# 실제 예보 자료 확인 실험 (사전 등록)

작성 2026-10-17. **이 문서와 `PartB/training/forecast_check.py`를 커밋한 뒤에** 실험을 한 번만 돌린다. 결과가 어떻게 나와도 그대로 보고한다.

## 1. 왜 하는가

본 실험과 시간 보류 확인(docs/temporal-check.md)은 모두 Open-Meteo **과거 분석 자료**(Historical Weather API, `ecmwf_ifs`)를 참값으로 썼다. 외부 검토에서 가장 자주 나온 지적은 "서비스가 실제로 받는 것은 예보인데, 분석 자료에서의 결론이 예보 자료에서도 성립하는가"였다.

서비스가 실제로 받는 **발행된 예보**(Open-Meteo Previous Runs API의 1일 전 예보 `precipitation_previous_day1`, 2024-06-01~2025-11-30, 같은 격자 셀 82개)로, 같은 조회 배치 비교를 다시 한다. 이 자료는 `PartB/data/cells_forecast_d1.parquet`에 이미 있고(2026-10-11, 카드 B9에서 내려받음), 지금까지 **경로 평균의 예보 오차(forecast_error.csv) 계산에만** 쓰였다. 어떤 배치 방법의 오차도 이 자료에서 계산된 적이 없다.

참값은 이 예보 자료의 **전수 조회 값**이다. 즉 "서비스가 예보 API에서 셀을 모두 조회했을 때 얻는 경로 평균"을 일부 셀 조회로 얼마나 복원하는지를 본다(예보 자체의 정확도는 다루지 않는다).

## 2. 고정하는 것

| 항목 | 값 |
| --- | --- |
| 기상 자료 | `PartB/data/cells_forecast_d1.parquet`(1일 전 예보, Open-Meteo best_match, 반환 좌표 = 격자 셀 확인됨), 2024-06-01~2025-11-30 UTC, 결측 0 |
| 경로 | 본 실험과 같은 `routes.parquet`(400개)와 `routes_holdout.parquet`(100개) |
| 대상 경로 | 지나는 셀 U ≥ 3 |
| 출발 시각 후보 | 본 실험 분할에서 **test**인 ISO 주의 현지 시각(IST) 06:00~23:00 정시(학습·검증 주는 쓰지 않는다), 도착까지 자료 범위 안 |
| 우천 표본 | 도착 시각 기준 예보 강수(본 실험과 같은 시간 선형 보간)가 0.1mm/h를 넘는 지점이 하나라도 있는 출발 시각 |
| 표본 추출 | 경로마다 우천 출발 시각 4개를 비복원 무작위 추출(`numpy.random.default_rng(20261017)`, 경로 순서는 (route_set, route_id) 정렬). 4개 미만이면 전부 |
| 모델 | `PartB/configs/model_a_frozen.json`의 동결 GP. 다시 학습하지 않는다 |
| 방법 | B1, M1, M2, H-P(논문의 Mid). `training.posthoc_placement.predict` 그대로 |
| 예산 | k/U = 0.25, 0.5, 0.75(본 실험과 같은 반올림) |
| 지표 | 표본별 경로 평균 강수 절대 오차 \|m̂ − m\| |
| 기술 통계(검정 없음) | 이전 방식(거리별 지점 4·6·9·12개, 최근접 값; `posthoc_extra.sample_count`)의 호출 수와 오차 |

## 3. 검정 (주 검정 2개, 시간 보류 확인과 같은 규칙)

| 이름 | 비교 | 예산 | 지지 조건 |
| --- | --- | --- | --- |
| F-1 | M2 − H-P | k/U = 0.5 | 양측 Wilcoxon 부호순위, Holm 보정 p < 0.05, 평균 차이 > 0 |
| F-2 | B1 − M2 | k/U = 0.5 | 같음 |

- Holm 보정은 F-1, F-2 두 개에만 적용한다. 평균 차이 95% 구간은 ISO 주 블록 부트스트랩(B = 2000, seed 42).
- 검정 함수는 `training.temporal_check`의 `evaluate`, `mae_table`, `tests_table`을 그대로 쓴다.

## 4. 논문에 쓸 문장 (결과 전에 정함)

- **둘 다 지지**: "서비스가 받는 1일 전 예보 자료(n = …)에서도 미리 정한 검정으로 지점 중앙 규칙이 M2보다, M2가 B1보다 오차가 작았다(… 대 … 대 …mm/h, Holm p …)."
- **하나라도 기각**: 기각된 비교를 그대로 적는다("예보 자료에서는 … 차이가 확인되지 않았다(…, p = …)"). 이 경우 해당 결론을 "분석 자료에서"로 한정해 쓴다.
- 어느 경우든 자료 종류(1일 전 예보), 표본 수, 사전 등록 사실을 함께 적는다.

## 5. 코드 확인 방법

실행 전 코드 점검은 `--smoke`로만 한다. 이때 출발 시각 후보는 **val** 주에서만 뽑고(테스트 주를 보지 않음) 표본 20개로 돌리며, 오차·검정 값은 출력하지 않고 표본 수와 행 수만 출력한다.

## 6. 산출물

- `PartB/training/forecast_check.py`
- `results/forecast_check/`: per_sample.csv.gz, mae.csv, tests.csv, previous.csv, summary.json(자료 SHA-256 포함)
