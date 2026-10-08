# 가격 상수 (카드 B5, 사전 등록)

> **이 문서와 `config/pricing-constants.json`은 2026-10-08에 동결했다. 이후 변경 금지.**
> 두 파일의 SHA-256은 `PartB/configs/model_a_frozen.json`에 기록되어 있다(`python -m training.freeze`).
> **논문은 절대 가격(₹)을 결론으로 쓰지 않는다.** 모델 A 평가와 메커니즘 실험은 강수 오차와 할증 판단으로 결론을 내며, 가격 수준은 예시다.

## 공식 (ml-design v5 §5.1)

```latex
\beta(r,s) = 1 + \min\big(\max(r - w\,s,\ 0)\times c_\beta,\ \mathrm{cap}\big)
```

```latex
\text{basePrice} = (\text{baseFee} + \text{perKm}\times d)\times \text{surge}(D,S)\times \beta(r,s),
\qquad \text{surge}=\mathrm{clip}\Big(\tfrac{D}{\max(S,1)},\ \text{surgeMin},\ \text{surgeMax}\Big)
```

- r = 경로 평균 강수 예측 m̂(mm/h), s = 사후 표본으로 구한 경로 평균의 표준편차. s = 0이면 β(r)와 같다.
- d = 경로 거리(km). D·S = 반경 5km 안 온라인 승객 수·ONLINE 기사 수(명세 v1.3 §4.8).
- surge는 0.1 단위로 반올림하고 실서비스에서만 쓴다. 모델 A 평가와 메커니즘 실험은 surge = 1로 고정한다.
- 할증 판단은 β > surchargeThreshold이다. 기본값(c_β = 0.15, cap 0.5, 임계 1.2)에서 s = 0이면 r > 4/3 mm/h가 할증이다.

## 키

| 키 | 값 | 의미 |
| --- | --- | --- |
| `version` | `"2026-10-08"` | 동결한 날짜 |
| `source` | Hans India 기사 URL | baseFee·perKm의 출처 (아래) |
| `baseFee` | 0 | 거리와 무관한 기본 요금(₹). 최소 요금을 선형식으로 바꾼 값 |
| `perKm` | 18 | km당 요금(₹) |
| `betaCoef` | 0.15 | c_β. 강수 1 mm/h당 할증 비율 |
| `betaCap` | 0.5 | 할증 상한. β ≤ 1.5 |
| `uncertaintyWeight` | 0.5 | w. 불확실성 s를 r에서 빼는 가중치 |
| `surchargeThreshold` | 1.2 | 할증 일치율·오할증률·미할증률의 기준. β > 1.2면 할증 |
| `surgeMin` / `surgeMax` | 0.7 / 3.0 | 수급 배수의 하한·상한 |
| `betaSensitivity` | [0.10, 0.15, 0.20, 0.30] | T2 민감도 표에서 다시 계산할 c_β 값들. 임계는 항상 1.2 |
| `servingBudgetRatio` | 0.5 | 실서비스에서 경로당 조회 예산 비율 k/U |
| `servingDraws` | 200 | 실서비스에서 s를 구하는 사후 표본 수(평가는 500) |

## baseFee·perKm의 출처와 변환

**출처**: 방갈로르(Bangalore Urban) 지역 교통 당국의 오토릭샤 요금 개정. 2025-07-15 발표, **2025-08-01 시행**.

| 항목 | 값 |
| --- | --- |
| 최소 요금 | ₹36 (첫 2km 포함, 이전 ₹30) |
| km당 요금 | ₹18 (2km 초과분, 이전 ₹15) |
| 적용 범위 | BBMP 관할 구역. 야간(22시~05시) 1.5배와 대기 요금은 이 상수에 넣지 않는다 |

- 주 출처(`source`): The Hans India, "Bengaluru Auto-Rickshaw Fares Increased from August 1, New Rates Announced", 2025-07-15 — https://www.thehansindia.com/bengaluru/bengaluru-auto-rickshaw-fares-increased-from-august-1-new-rates-announced-988249 (발표 기관을 Bangalore Urban 지역교통청(RTA)으로 적음).
- 교차 확인: Deccan Herald, "Bengaluru auto fares to increase from August 1" — https://www.deccanherald.com/india/karnataka/bengaluru/bengaluru-auto-fares-to-increase-from-august-1-3630129 (지구교통청(DTA) 고시로 적음). Deccan Herald는 자동 조회를 막아(403) 검색 요약으로만 수치를 확인했다. 같은 수치를 The Logical Indian, The Daily Jagran도 보도했다.
- 발표 기관 이름은 매체마다 RTA/DTA로 다르다. 원 고시문(관보)은 찾지 못했다.
- 2026-10-08 검색에서 그 뒤의 개정은 찾지 못했다.

**변환**(카드 B5 규칙): perKm = km당 요금 = 18. baseFee = 최소 요금 − perKm × 포함 km = 36 − 18 × 2 = **0**. 따라서 기본 요금 = 18 × d. 2km 미만 이동에서는 실제 최소 요금(₹36)보다 낮게 나오지만, 데이터의 경로는 모두 5km 이상이라 영향이 없다.

이전 개정(2021-11, 최소 ₹30에 1.9km 포함, km당 ₹15)과 ml-design v5의 예시 상수(₹30 + ₹15/km)는 쓰지 않는다.
