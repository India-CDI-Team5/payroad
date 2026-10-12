# PayRoad

승객과 기사가 가격을 흥정하는 차량 호출 서비스입니다. 경로의 강수 예보로 기준가를 정하고, 승객은 여러 기사의 호가 중 가격과 픽업 거리를 보고 골라 체결합니다.

경북대학교와 인도 Christ University가 함께 연 CDI 프로그램에서 시작한 프로젝트입니다(한국 2명·인도 2명 팀, International Conference on Climate Justice 2026 포스터 발표). 이후 한국 팀원 2명이 연구를 이어 가고 있습니다.

## 주요 기능

- **실시간 흥정**: 승객이 거래를 열면 주변 기사들이 호가를 내고, 승객은 가격과 픽업 예상 시간을 함께 보고 호가를 고르거나 직접 가격을 제안합니다. 흥정 규칙은 R1~R13 13개이고, 화면 갱신은 WebSocket(STOMP)으로 합니다.
- **날씨를 반영한 기준가**: 경로가 지나는 기상 격자 셀 중 일부만 조회해 경로 강수를 추정합니다. 조회 위치는 셀 단위로 고르고, Gaussian Process의 사후 분산이 큰 셀을 추가로 조회한 뒤 나머지를 GP로 보간합니다. 추정값과 불확실성으로 강수 할증을 정합니다.
- **메커니즘 실험**: 실서비스와 같은 흥정 규칙 위에서 기사·승객 봇을 가상 시계로 돌려, 경쟁 기사 수·규칙 파라미터·날씨·담합이 체결에 주는 영향을 측정합니다(실험 E1~E7).
- **담합 탐지**: 시뮬레이터에 담합 기사 집단을 심고, 행동 로그만으로 담합 기사를 찾는 모델을 학습합니다. 학습에 쓰지 않은 담합 전략으로 평가합니다.

## 구조

| 디렉터리 | 내용 | 기술 |
|---|---|---|
| `PartA` | 흥정 서버, 실험 러너와 봇(담합 전략 포함), 데모 화면 | Java 21, Spring Boot 3.4, Redis 7.4(Lua), WebSocket(STOMP) |
| `PartB` | 경로 기상 수집, 강수 보간, 기준가 API | Python, FastAPI, NumPy·SciPy(Gaussian Process 직접 구현) |
| `collusion` | 행동 로그 피처 추출과 담합 탐지 모델 학습·평가 | Python, scikit-learn |
| `config`, `data` | 동결된 가격 상수, 실험 봇·담합 파라미터, 실험용 거래 목록 | |
| `docs` | API 명세, 가격 상수 출처, 기상 격자 실측, 그림 원본(draw.io), 파일럿 진행 규약 | |
| `results`, `scripts` | 실험 결과와 요약·그림·표 생성 스크립트 | |

## 핵심 설계

- **게시판형 흥정**: 기사마다 활성 호가는 1개이고, 승객이 호가를 지목해 수락합니다. 각자 자기 가격을 양보하는 방향으로만 바꿀 수 있어서 협상이 수렴합니다.
- **규칙은 Redis Lua 스크립트 한 벌에만 있습니다.** 스크립트 한 번이 읽기·판정·쓰기를 끝내므로, 서버가 여러 대여도 원자성은 Redis가 보장합니다.
- **만료는 Redis TTL이 아니라 호출자가 넘기는 현재 시각으로 판정합니다.** 그래서 실서비스(벽시계)와 실험(가상 시계)이 같은 스크립트를 씁니다.
- **기준가** = (기본요금 + km당 요금 × 거리) × 수급 할증 × 강수 할증 β(r, s). r은 경로 평균 강수 예측, s는 그 불확실성입니다. Part B가 응답하지 않으면 폴백 가격을 쓰고, 응답의 `priceSource`(`QUOTE` / `FALLBACK`)로 구분합니다.
- **사전 등록**: 가격 상수, 평가 계획, 봇 파라미터, 탐지 모델을 결과를 보기 전에 해시와 함께 동결했습니다(`PartB/configs/model_a_frozen.json`, `collusion/configs/collusion_frozen.json`).

자세한 규칙과 API는 [docs/api-spec.md](docs/api-spec.md)에 있습니다.

## 실행

```bash
docker compose up -d redis                       # Redis 7.4 (localhost:6379)

cd PartB
pip install -r requirements.txt
python -m uvicorn app:app --port 8000            # 기준가 API

cd PartA
./gradlew bootRun                                # 흥정 서버와 데모 화면, 저장소 루트 .env에 ORS_API_KEY 필요
```

- 경로 계산에는 OpenRouteService API 키가 필요합니다. 저장소 루트에 `.env` 파일을 만들고 `ORS_API_KEY=...`를 넣으세요.
- `/quote`에는 기상 격자 파일 `PartB/data/grid_cells.json`이 필요합니다. 격자 좌표 82개만 담은 작은 파일이라 저장소에 포함되어 있습니다(`PartB/data/`의 다른 파일은 gitignore). 다시 만들려면 `cd PartB && python -m training.meteo_probe`를 실행합니다. 파일이 없으면 `/quote`는 502를 돌려주고, Part A는 폴백 기준가로 동작합니다.

## 테스트와 실험

```bash
cd PartA && ./gradlew test                       # Redis DB 15 사용
cd PartB && python -m pytest
python -m pytest collusion scripts               # 저장소 루트에서

cd PartA && ./gradlew runExperiment --args="--scenario e2"   # 실험 러너, Redis DB 14 사용
python scripts/sim/summarize.py                  # results/sim/ 요약 CSV
python scripts/figures/make_all.py               # 그림·표 (results/figures/MANIFEST.txt에 SHA-256)
```

실험 원시 출력(`results/sim/raw/`)은 저장소에 올리지 않습니다. 같은 seed로 다시 실행하면 같은 파일이 나옵니다.

실험 결과와 코드는 태그 `v1.0-paper`로 동결했습니다. 이 태그를 깨끗하게 클론해 위 테스트가 모두 통과하고, `make_all.py`가 다시 만든 그림·표의 SHA-256이 `results/figures/MANIFEST.txt`와 같은 것을 확인했습니다. `PartB/data/`의 학습용 원자료(parquet)는 저장소에 없어서 모델 A를 처음부터 다시 학습하려면 `PartB/training/`의 수집 스크립트를 먼저 실행해야 합니다.

## 문서

| 문서 | 내용 |
|---|---|
| [docs/api-spec.md](docs/api-spec.md) | 흥정 규칙 R1~R13, REST·STOMP API, Redis 키 구조, 오류 코드 |
| [docs/pricing-constants.md](docs/pricing-constants.md) | 기준가 상수와 출처(벵갈루루 오토릭샤 요금) |
| [docs/weather-grid-resolution.md](docs/weather-grid-resolution.md) | 기상 API 격자 해상도 실측 |
| [docs/collusion-s5.md](docs/collusion-s5.md) | 블라인드 평가용 담합 전략 S5 |
| [docs/pilot-protocol.md](docs/pilot-protocol.md) | 사용자 파일럿 진행 규약(이번 연구에서는 진행하지 않음) |
| `docs/figures_src/` | 시스템 구조도·상태 전이도 원본(diagrams.net) |
