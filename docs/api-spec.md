# PayRoad — 흥정 규칙 및 API 명세서 v1.3

> **상태**: v1.3 확정 (2026-10-06 팀 합의)
> **동결 범위**: §2 규칙, §4~§5 형식, §6.6 Lua 계약은 **2026-10-14 코드 동결까지 변경 금지**. 바꿔야 하면 두 사람이 모두 승인하고 이 문서의 버전을 올린다.
> **함께 보는 문서**: PayRoad 리팩터링 계획 v6, ML 설계 및 데이터 전략 v5, 마일스톤 v5 (각자 `docs/plan/`에 둔다)

### v1.2 → v1.3 변경 이력 (2026-10-06)

| # | 변경 | 이유 | 위치 |
|---|---|---|---|
| 1 | **저장소를 Redis로 확정.** 흥정 규칙 R1~R13은 **Redis Lua 스크립트 한 벌**에만 구현한다. 스크립트 한 번이 읽기·판정·쓰기를 모두 끝낸다. Java의 `DealStateMachine`·`MarketStateMachine`은 삭제한다 | 현업 구조(서버 여러 대 + Redis)를 따른다. 원자성을 Java `synchronized`가 아니라 Redis가 보장한다. 동시 요청이 몰려도 재시도(낙관적 잠금 충돌)가 없다 | R9, §6.1, §6.6 |
| 2 | **Redis TTL(`EXPIRE`)을 쓰지 않는다.** 모든 만료는 필드에 적힌 시각(`expiresAt` 등)과, 호출자가 인자로 넘기는 현재 시각 `nowMs`로 판정한다. 만료 처리는 스윕 스크립트(`sweep.lua`)가 한다 | 실서비스(벽시계)와 실험 러너(가상 시계)가 같은 스크립트를 쓰기 위해서다. Redis 자체 시계를 쓰면 가상 시계가 깨진다 | R6, R7, §6.5 |
| 3 | **R5 이탈 처리를 삭제했다.** 거래·호가에 참여 중인 사용자는 heartbeat가 끊겨도 오프라인으로 내리지 않는다 | 이탈 비율을 정의·모델링하지 않고 핵심(흥정 규칙·모델)에 집중한다. 남은 거래는 R7(180초)로 반드시 끝난다 | R5, §3, §6.5, §8 |
| 4 | `reason` 값 **`DRIVER_DISCONNECTED`, `RIDER_DISCONNECTED`를 삭제**했다 | 3번의 결과 | §5.3, §6.4 |
| 5 | **R13 신설**: 기사 한 명의 동시 활성 호가는 최대 **50건**. 에러 코드 `MAX_ACTIVE_BIDS_EXCEEDED` | R10 정리 루프(Lua 안 반복문)의 반복 횟수를 상수로 묶는다 | R13, §5.5 |
| 6 | **수급 정의를 확정했다.** demand = 반경 5km 안 온라인 승객 수(요청자 포함), supply = 반경 5km 안 ONLINE 기사 수. 데모에서는 **가상 접속 인구(일반 사용자 5%, 기사 70% 동시 접속)**가 채운다 | 실서비스 화면을 현실적으로 채운다. 논문 실험은 surge = 1로 고정하므로 결과에 영향이 없다 | §4.8, §6.7 |
| 7 | 스윕 주기를 **1초**로 바꿨다. 스윕이 하는 일은 거래 만료(R7), 오퍼 만료(R6), presence 정리, 종료 거래 물리 삭제다 | 오퍼 TTL 30초를 1초 정밀도로 지킨다 | §6.5 |
| 8 | `POST /api/deals` 응답에 **`priceSource`**(`QUOTE` 또는 `FALLBACK`)를 추가했다 | Part B `/quote` 실패 시 폴백 가격을 구분한다 | §4.1 |
| 9 | heartbeat는 활성 호가의 픽업 거리를 **갱신하지 않는다.** 픽업 거리는 호가 제출 시점 좌표로 계산한다 | v1.2의 모호한 문장을 정리했다. 기사가 위치를 바꾸려면 호가를 다시 낸다 | §4.7, §6.2 |
| 10 | `/topic/market/{geohash}` 브로드캐스트와 rate limit(분당 10회)은 **정의만 유지하고 이번 구현 범위에서 뺀다** | UI는 3초 폴링으로 충분하고, 봇은 악용하지 않는다 | §5.4, §5.5, R8 |
| 11 | 테스트 시나리오 18종 → **20종** | 3·5번 반영 | §8 |
| 12 | `deal:{dealId}:bidsByPrice`(ZSet)를 **쓰지 않는다.** 순위는 `:bids` Hash를 (가격, seq)로 정렬해 구한다 | 부동소수 가격의 동률 처리를 Java 구현과 똑같이 맞춘다 | §6.1, §6.6 |
| 13 | **운행 완료 가정**: 체결된 기사는 그 거래 키가 물리 삭제될 때(생성 후 300초) `MATCHED`가 풀리고 ONLINE으로 돌아온다 | 데모·파일럿에서 같은 기사 ID를 다시 쓸 수 있게 한다. 운행 자체는 범위 밖 | R10, §6.5 |

### v1.1 → v1.2 추가 사항 (구현 반영, 기존 필드 변경 없음)

| # | 추가 | 위치 |
|---|---|---|
| 1 | `error` 이벤트 구독 경로를 **`/user/queue/errors`**로 명시 (STOMP 세션 단위 전달) | §5.1, §5.3 |
| 2 | 승객 취소에 **`?riderId=` 쿼리 파라미터** 추가 (인증 부재로 본인 확인용) | §4.3 |
| 3 | 라운드 상한(R8)에 걸린 행위는 반영하지 않고 거래를 `EXPIRED(ROUND_LIMIT)`로 종료하며, 요청자에게 `ROUND_LIMIT_EXCEEDED` 전송 | R8, §5.3 |

### v1.0 → v1.1 변경 이력

| # | 변경 | 위치 |
|---|---|---|
| 1 | 에러 이벤트 `currentVersion` → **`version`**으로 통일 | §5.3 |
| 2 | WebSocket 호가 요청 좌표를 **`driverLat`/`driverLng`**로 통일 | §5.2 |
| 3 | heartbeat 이탈 처리 방식을 10초 주기 스윕 잡으로 확정 (v1.3에서 이탈 처리 삭제) | R5, §6.5 |
| 4 | 승객 heartbeat 이탈 처리 신설 (v1.3에서 삭제) | R5, §8 |
| 5 | R8 라운드 카운트에서 **철회 제외** 명시 | R8 |
| 6 | 테스트 시나리오 16종 → 18종 | §8 |

---

## 0. 설계 요약

**여러 호가가 동시에 살아 있는 게시판 모델**이다. 승객은 가격과 픽업 거리를 함께 보고 호가를 고르고, 기사는 승객 오퍼를 먼저 받아 체결할 수도 있다.

| | 이전 설계 | 확정 설계 |
|---|---|---|
| 가격 표현 | `currentPrice` 단일값 | **활성 호가 목록** (기사당 1개) |
| 수락 대상 | 최저가 기사 자동 지정 | **승객이 호가를 지목해 수락** |
| 선택 기준 | 가격 단일 | **가격 + 픽업 거리/ETA** (승객 판단) |
| 턴 | 하드 잠금 (턴 소유자만 수락) | **응답 대기 표시** (UI 힌트 + 타임아웃 트리거) |
| 가격 개선 | 전역 강제 (현재가보다 유리해야) | **행위자별 단조성** (자기 호가만 양보 방향) |
| 규칙 구현 위치 🆕 v1.3 | Java 상태머신 + `synchronized` | **Redis Lua 스크립트 한 벌** (실서비스·실험 러너 공용) |

**행위자별 단조성을 남긴 이유**: 전역 가격 개선을 버리면 협상이 발산할 수 있다. 각 참여자가 자기 호가를 양보 방향으로만 갱신하게 하면 **수렴성은 그대로 보장**되면서 가격 다양성은 살아난다.

**아키텍처 한 줄** 🆕 v1.3: 모든 거래·호가·presence 상태는 Redis에만 있다. Spring Boot 서버는 상태를 들고 있지 않고, 명령마다 Lua 스크립트를 한 번 실행한 뒤 결과 이벤트를 STOMP로 내보내고 종료된 거래를 `DealHistory`(H2)에 기록한다. 실험 러너도 같은 Lua 스크립트를 같은 순서로 호출한다.

---

## 1. 도메인 개념 정의

### 1.1 거래(Deal)

승객 1명의 특정 출발지 → 목적지 이동 요청. 시스템이 기준가를 붙여 시장에 게시한다.

### 1.2 기사 호가(DriverBid)

한 기사가 "이 가격이면 태우겠다"고 제시한 것. **한 거래 안에서 기사당 최대 1개의 활성 호가**만 유지되며, 새 호가는 이전 호가를 대체한다. 한 기사는 여러 거래에 동시에 호가할 수 있다(최대 50건, R13).

```
{ bidId, driverId, price, driverLat, driverLng,
  pickupDistanceKm, pickupEtaMin, createdAt }
```

`pickupDistanceKm`와 `pickupEtaMin`은 서버(Lua)가 호가 제출 시점 좌표로 계산한다(§6.2).

### 1.3 승객 오퍼(RiderOffer)

승객이 "이 가격이면 타겠다"고 전체 기사에게 공개 제시한 것. **거래당 최대 1개**만 존재하며, 새 오퍼가 이전 것을 대체한다.

```
{ price, createdAt, expiresAt }
```

### 1.4 체결 경로 (2가지)

| 경로 | 행위 | 결과 |
|---|---|---|
| **A. 승객 지목 수락** | 승객이 특정 기사의 호가를 선택 | 그 기사와 그 가격으로 체결 |
| **B. 기사 선착 수락** | 기사가 승객 오퍼를 수락 | 먼저 처리된 기사와 오퍼 가격으로 체결 |

두 경로가 동시에 발생할 수 있으므로 원자적 단일 체결이 필수다(R9).

### 1.5 참여 중 🆕 v1.3

R5·R11이 쓰는 정의다.

| 대상 | 참여 중인 조건 |
|---|---|
| 승객 | 자기 거래 중 상태가 `OPEN` 또는 `NEGOTIATING`인 것이 있다 |
| 기사 | 활성 호가가 1건 이상 있다(`driver:{id}:deals`가 비어 있지 않음) 또는 상태가 `MATCHED`다 |

> 구현은 승객의 **가장 최근 거래**(`presence:rider:{id}`의 `activeDealId`)만 본다. 그 거래가 물리 삭제됐으면 참여 중이 아니다. 한 승객이 동시에 거래 둘을 여는 경우는 다루지 않는다(허용된 단순화).

---

## 2. 흥정 규칙 R1~R13

### R1. 행위자별 단조성 (Per-Actor Monotonicity)

| 대상 | 제약 |
|---|---|
| 기사 | 자신의 직전 호가보다 **낮거나 같아야** 함 (`newPrice ≤ myLastBid`) |
| 승객 | 자신의 직전 오퍼보다 **높거나 같아야** 함 (`newPrice ≥ myLastOffer`) |

- **다른 기사의 호가와는 비교하지 않는다.** 최저가보다 비싼 호가도 정상 접수된다.
- 첫 호가/오퍼에는 적용되지 않는다.
- **철회 후 재입찰 시에도 직전 호가 기준을 유지한다** (철회로 제약을 리셋할 수 없음).
- 위반 시 거부: `PRICE_NOT_CONCEDED`

> **근거**: 낮은 가격으로 유인한 뒤 올리는 행위(bait) 차단 + 협상 수렴 보장

### R2. 호가 밴드

```
basePrice × 0.7 ≤ price ≤ basePrice × 3.0
```

- 승객 오퍼·기사 호가 모두에 적용
- 위반 시 거부: `OUT_OF_BAND`

### R3. 수락 권한

- **승객**: 활성 기사 호가 중 **아무거나** 지목해 수락 가능. 상시 가능
- **기사**: 승객 오퍼가 존재하고 만료되지 않았을 때만 수락 가능. 상시 가능
- 하드 턴 잠금 없음

### R4. 응답 대기 표시 (pendingSide) — UI 전용

마지막 행위의 반대편을 `pendingSide`로 표시한다. **수락 권한을 제한하지 않으며**, 화면의 "지금 응답을 기다립니다" 표시와 타임아웃(R6) 트리거로만 사용한다.

| 마지막 행위 | `pendingSide` |
|---|---|
| 기사 호가 제출 | `RIDER` |
| 승객 오퍼 게시 | `DRIVER` |
| 승객 오퍼 만료 | `RIDER` |
| 거래 생성 직후 | `DRIVER` |

### R5. 활성 호가 관리와 참여 중 이탈 없음 🔄 v1.3

**호가 관리**
- 한 거래 안에서 기사당 활성 호가 1개. 새 호가는 이전 것을 **대체**(replace)하고 새 `bidId`를 받는다(승객이 보지 못한 가격을 수락하지 않게).
- 기사가 호가를 철회(`WITHDRAW`)하면 목록에서 제거한다.

**참여 중 이탈 없음 (가정)**
- **참여 중인 사용자(§1.5)는 heartbeat가 끊겨도 ONLINE으로 본다.** 서버는 이탈을 이유로 호가를 철회하거나 거래를 취소하지 않는다.
- 참여 중이 아닌 사용자는 마지막 heartbeat 후 60초가 지나면 다음 스윕에서 오프라인이 된다(presence 삭제).
- 남은 거래는 R7(거래 TTL 180초)로 반드시 끝난다. 이것이 이탈에 대한 유일한 안전망이다.

> **근거**: 앱을 쓰다가 나가는 사용자는 끝까지 쓰는 사용자보다 훨씬 적다. 그 비율을 정의하고 시뮬레이션하려면 다뤄야 할 경우가 크게 늘어난다. 이번 범위는 흥정 규칙과 모델에 집중한다.
> **알려진 한계**: 앱을 끈 기사의 호가가 최대 180초 동안 남아, 승객이 그 호가를 수락할 수 있다. 논문 한계 절에 한 줄로 적는다.

### R6. 타임아웃

| 대상 | 값 | 만료 시 동작 |
|---|---|---|
| 승객 오퍼 TTL | **30초** | 오퍼 소멸, `pendingSide = RIDER`로 전환, `offer.expired` |
| 응답 대기 알림 | **15초** | UI 카운트다운 종료. 거래는 유지, 상태 변화 없음 (서버는 관여하지 않음) |

- 판정: `nowMs ≥ offerExpiresAt`이면 만료다. 만료된 오퍼에 대한 수락은 스윕 전이라도 `OFFER_EXPIRED`로 거부한다. 오퍼 제거와 `offer.expired` 이벤트는 스윕(§6.5)이 만든다.

> 승객 오퍼에 별도 TTL을 둔 이유: 승객이 잊고 방치한 오퍼를 기사가 뒤늦게 수락하는 상황 차단

### R7. 거래 TTL 🔄 v1.3

**180초**. 만료 시 `EXPIRED`. 활성 호가가 있어도 만료된다.

- 판정: `nowMs ≥ expiresAt`이면 만료다. 만료 시각이 지난 거래에 대한 모든 행위는 스윕 전이라도 `DEAL_NOT_ACTIVE`로 거부한다. 상태 전이와 `deal.expired(TTL)` 이벤트는 스윕(§6.5)이 만든다.
- **물리 삭제**: 거래 키(`deal:{dealId}` 계열)는 `purgeAt = createdAt + 300초`에 스윕이 지운다. 논리적 만료(180초)와 물리 삭제(300초) 사이 **120초 grace period** 동안 `GET /api/deals/{dealId}`가 마지막 상태를 돌려준다. Redis `EXPIRE`는 쓰지 않는다(§6.1).

### R8. 라운드 상한 🔄 v1.1

**20회**에 도달한 뒤 다음 라운드 행위가 오면 그 행위는 반영하지 않고 거래를 `EXPIRED(ROUND_LIMIT)`로 종료한다. 요청자에게는 `ROUND_LIMIT_EXCEEDED`를 보낸다(v1.2).

**카운트 대상**
- ✅ 기사 호가 제출 (갱신 포함, 각각 1회)
- ✅ 승객 오퍼 게시 (갱신 포함, 각각 1회)

**카운트 제외**
- ❌ **호가 철회 (`WITHDRAW`)**
- ❌ R10에 의한 자동 철회 (`DRIVER_MATCHED_ELSEWHERE`)
- ❌ 승객 오퍼 TTL 만료

> **근거**: 라운드 상한의 목적은 무한 협상 방지다. 철회는 협상을 진전시키는 행위가 아니라 이탈이며, 이를 카운트하면 실수로 철회 후 재입찰한 성실한 참여자가 불이익을 받는다. 철회-재입찰 반복 악용은 rate limit(기사당 분당 10회)으로 막도록 정의하되, **이번 구현 범위에서는 만들지 않는다** 🔄 v1.3.

### R9. 단일 체결 (원자성) 🔄 v1.3

동시에 여러 수락이 들어와도 **정확히 1건만** 성공한다. 실패한 쪽은 `DEAL_ALREADY_MATCHED`.

적용 대상:
- 기사 2명이 동시에 승객 오퍼 수락
- 승객 지목 수락과 기사 선착 수락이 동시 발생

**보장 방식**: 수락은 Lua 스크립트(`accept_bid.lua`, `accept_offer.lua`) 한 번 안에서 상태 확인 → 체결 → R10 정리까지 끝난다. Redis는 스크립트를 하나씩 순서대로 실행하므로, 먼저 실행된 스크립트가 거래를 `MATCHED`로 바꾸면 뒤의 스크립트는 `DEAL_ALREADY_MATCHED`를 받는다. 클라이언트가 보낸 `version`이 현재와 다르면 `VERSION_CONFLICT`다(§5.6).

### R10. 기사 이중 체결 차단

한 기사가 여러 거래에 호가를 낼 수 있다. 어느 한 거래가 체결되면, **같은 스크립트 안에서** 그 기사의 다른 모든 활성 호가를 철회하고(`bid.withdrawn`, `reason=DRIVER_MATCHED_ELSEWHERE`) 기사 상태를 `MATCHED`로 바꾼다. 여기서 "활성"은 상태가 `OPEN`/`NEGOTIATING`인 것이며 만료 시각은 보지 않는다(Java `forceWithdraw`와 같음). R13 때문에 이 정리 루프는 **최대 50회** 돈다(오퍼 수락으로 체결됐고 그 거래에 자기 호가가 없으면 50회, 그 밖에는 49회).

`MATCHED`는 체결된 거래의 키가 물리 삭제될 때(생성 후 300초, §6.5 4단계) 풀린다(운행 완료 가정 🆕 v1.3).

### R11. 참여 자격 🔄 v1.3

- 기사는 **`MATCHED`가 아니고, ONLINE일 때만** 호가·철회·오퍼 수락을 할 수 있다. ONLINE = presence가 만료되지 않았거나(`expiresAt > nowMs`) 참여 중(§1.5). 위반 시 `DRIVER_NOT_AVAILABLE`.
- 승객은 자신의 거래에만 오퍼·지목 수락·취소를 할 수 있다. 위반 시 `NOT_DEAL_OWNER`.
- 거래 상태가 `OPEN` 또는 `NEGOTIATING`이고 만료 시각 전일 때만 모든 행위가 허용된다.
- 거리 제한은 없다. 기사는 `/api/market`에 보이는 거래에 호가할 수 있다(보이는 범위: 반경 10km, §4.4).

### R12. 승객 취소

승객은 체결 전까지 언제든 취소 가능 → `CANCELLED`. 모든 활성 호가와 오퍼가 함께 사라진다. `deal.expired(reason=CANCELLED_BY_RIDER)`.

### R13. 기사당 동시 활성 호가 상한 🆕 v1.3

기사 한 명이 **동시에** 활성 호가를 걸어둘 수 있는 거래는 최대 **50건**이다.

- 검사 시점: 이 기사가 **이 거래에 살아 있는 호가가 없을 때**(`SISMEMBER driver:{driverId}:deals dealId = 0`)만 검사한다. 철회한 뒤 다시 호가하는 경우도 여기에 해당한다. 살아 있는 호가의 가격을 갱신하는 것은 건수가 늘지 않으므로 검사하지 않는다.
- 판정: `SCARD driver:{driverId}:deals ≥ 50`이면 거부 `MAX_ACTIVE_BIDS_EXCEEDED`. 다른 키를 고치기 전에 검사한다.
- 건수가 줄어드는 때: 철회, 그 거래의 종료(체결·만료·취소), R10 정리. 이때 `driver:{driverId}:deals`에서 그 거래를 뺀다.

> **근거**: R10 정리 루프는 Lua 스크립트 안에서 돈다. Redis는 스크립트 하나를 실행하는 동안 다른 모든 요청을 멈춘다. 기사 한 명의 활성 호가 수에 상한이 없으면 이 루프가 얼마나 길어질지 알 수 없다. 상한을 상수로 정해 반복 횟수를 최대 50회로 묶는다.
> **표현 규칙**: 논문·발표에서 이 상한을 "O(n)을 O(1)로 개선"처럼 복잡도 개선으로 쓰지 않는다. "반복 횟수의 상한(기사당 활성 호가 50건)"으로만 쓴다.

**예비 측정** (팀원 브랜치 `gutae_edition`의 `PartA/scripts/redis-bench/`, 로컬 Redis 8.4.0, R10 정리 루프만 분리해 `redis-cli` 호출 전후 벽시계로 측정. 기준값에 프로세스 기동·연결 비용이 포함됨)

| 기사당 활성 호가 수 N | 평균 소요 시간 | 기준(N=1) 대비 증가분 |
|---|---|---|
| 1 | 7.50ms | 기준 |
| 50 (R13 상한) | 7.53ms | 약 0.03ms, 기준과 구분되지 않음 |
| 1,000 | 8.11ms | 약 0.6ms |
| 10,000 | 17.19ms | 약 9.7ms |
| 100,000 | 75.92ms | 약 68ms |
| 1,000,000 | 1044.62ms | 약 1.04초 |

비용은 N에 대략 선형으로 늘어난다. N = 1,000,000이면 스크립트 한 번이 약 1초 걸리고, 그동안 Redis의 모든 요청이 멈춘다.

---

## 3. 상태 전이 🔄 v1.3

```
                      ┌─── 호가 없이 TTL 만료 ───┐
                      │                          ▼
[거래 생성] ──► OPEN ──첫 호가/오퍼──► NEGOTIATING ──수락──► MATCHED
                      │                    │  ▲
                      │                    └──┘   EXPIRED ◄── TTL/라운드 초과
                      │              호가·오퍼 반복
                      └── 승객 취소 ──► CANCELLED
```

| 상태 | 의미 | 허용 행위 |
|---|---|---|
| `OPEN` | 게시됨, 아직 호가·오퍼 없음 | 기사 호가, 승객 오퍼, 승객 취소 |
| `NEGOTIATING` | 호가 또는 오퍼가 한 번이라도 있었음 | 호가 갱신·철회, 오퍼 갱신, 양측 수락, 승객 취소 |
| `MATCHED` | 체결 완료 | 없음 (종료) |
| `EXPIRED` | TTL 또는 라운드 초과 | 없음 (종료) |
| `CANCELLED` | 승객 취소 | 없음 (종료) |

> v1.3에서 "승객 이탈 → CANCELLED" 전이를 삭제했다(R5).

---

## 4. REST API

### 4.1 `POST /api/deals` — 거래 생성 🔄 v1.3

**요청**
```json
{
  "riderId": "R001",
  "origin": { "lat": 12.9716, "lng": 77.5946 },
  "dest":   { "lat": 12.9352, "lng": 77.6245 }
}
```

**응답 201**
```json
{
  "dealId": "D-7f3a9c",
  "status": "OPEN",
  "basePrice": 184.5,
  "priceBand": { "min": 129.15, "max": 553.5 },
  "distanceKm": 8.42,
  "durationMin": 24.3,
  "avgRainMm": 1.2,
  "weatherFactor": 1.18,
  "priceSource": "QUOTE",
  "routePolyline": "encoded_polyline_string",
  "pendingSide": "DRIVER",
  "round": 0,
  "version": 1,
  "createdAt": "2026-09-15T04:12:33Z",
  "expiresAt": "2026-09-15T04:15:33Z"
}
```

- `priceSource` 🆕 v1.3: `QUOTE`(Part B `/quote`가 2초 안에 응답) 또는 `FALLBACK`(직선거리 × 1.3, 날씨 미반영).
- 거래 생성은 `create_deal.lua` 한 번으로 한다. 같은 스크립트가 `deals:expiry`, `deals:purge`, `geo:deals`에 거래를 넣는다(§6.1). 거래를 만든 승객은 presence가 자동 등록된다.

### 4.2 `GET /api/deals/{dealId}` — 거래 상태 조회

**응답 200**
```json
{
  "dealId": "D-7f3a9c",
  "status": "NEGOTIATING",
  "basePrice": 184.5,
  "priceBand": { "min": 129.15, "max": 553.5 },
  "distanceKm": 8.42,
  "bids": [
    {
      "bidId": "B-001", "driverId": "DR042", "price": 190.0,
      "driverLat": 12.9401, "driverLng": 77.6102,
      "pickupDistanceKm": 4.8, "pickupEtaMin": 11.2,
      "createdAt": "2026-09-15T04:12:50Z"
    },
    {
      "bidId": "B-002", "driverId": "DR017", "price": 215.0,
      "driverLat": 12.9720, "driverLng": 77.5951,
      "pickupDistanceKm": 0.3, "pickupEtaMin": 1.4,
      "createdAt": "2026-09-15T04:13:02Z"
    }
  ],
  "riderOffer": { "price": 175.0, "createdAt": "...", "expiresAt": "..." },
  "lowestBidPrice": 190.0,
  "bidderCount": 2,
  "pendingSide": "DRIVER",
  "round": 3,
  "version": 7,
  "expiresAt": "2026-09-15T04:15:33Z"
}
```

- `bids` 배열은 **가격 오름차순**, 같은 가격이면 먼저 낸 호가(`seq`가 작은 것)가 앞이다(§6.6의 순위 규칙). 클라이언트가 `pickupEtaMin` 기준으로 재정렬할 수 있도록 두 값을 모두 내려준다.
- 조회는 읽기 전용 스크립트 `get_deal.lua` 한 번으로 한다(여러 키를 따로 읽다가 중간에 쓰기가 끼어드는 것을 막는다).
- 물리 삭제(`purgeAt`) 뒤에는 404.

### 4.3 `DELETE /api/deals/{dealId}` — 승객 취소

**요청**: `?riderId=R001` (v1.2) — 거래의 승객만 취소할 수 있다(`NOT_DEAL_OWNER` → 403). 취소는 `version`을 검사하지 않는다.

**응답 200**: `{ "dealId": "...", "status": "CANCELLED", "version": 8 }`

### 4.4 `GET /api/market` — 주변 시장 스냅샷

**요청**: `?lat=12.97&lng=77.59&limit=30`

**응답 200**
```json
{
  "deals": [
    {
      "dealId": "D-7f3a9c",
      "originApprox": { "lat": 12.972, "lng": 77.595 },
      "destApprox":   { "lat": 12.935, "lng": 77.625 },
      "distanceKm": 8.42,
      "basePrice": 184.5,
      "lowestBidPrice": 190.0,
      "riderOfferPrice": 175.0,
      "bidderCount": 2,
      "pendingSide": "DRIVER",
      "expiresAt": "2026-09-15T04:15:33Z",
      "version": 7
    }
  ],
  "cells": ["tdr1v", "tdr1u", "tdr1y"],
  "generatedAt": "2026-09-15T04:13:10Z"
}
```

- 대상: 상태가 `OPEN`/`NEGOTIATING`이고 출발지가 요청 좌표에서 **10km 안**인 거래, 가까운 순 `limit`개. Redis `GEOSEARCH geo:deals FROMLONLAT … BYRADIUS 10 km ASC COUNT limit`로 찾는다.
- 좌표는 소수 셋째 자리(약 100m)로 반올림(프라이버시). `cells`는 요청 좌표의 geohash(정밀도 5)와 주변 8칸이다. 클라이언트는 이 API를 **3초마다 폴링**한다(§5.4 미구현).

### 4.5 `POST /api/presence/driver` — 기사 온라인 등록

**요청**: `{ "driverId": "DR042", "driverLat": 12.97, "driverLng": 77.59 }`
**응답**: `{ "driverId": "DR042", "status": "ONLINE", "expiresAt": "..." }`

- `status`는 `MATCHED` 기사면 `MATCHED`를 돌려준다. `expiresAt` = 지금 + 60초.

### 4.6 `POST /api/presence/rider` — 승객 온라인 등록 (v1.1)

**요청**: `{ "riderId": "R001" }`
**응답**: `{ "riderId": "R001", "status": "ONLINE", "expiresAt": "..." }`

> 거래 생성 시 자동으로 등록되지만, 명시적 등록 엔드포인트도 제공한다(재접속 시).

### 4.7 `POST /api/presence/heartbeat` — 생존 신호 🔄 v1.3

**요청**
```json
{ "actorId": "DR042", "actorType": "DRIVER", "driverLat": 12.97, "driverLng": 77.59 }
```
승객의 경우 좌표는 생략 가능:
```json
{ "actorId": "R001", "actorType": "RIDER" }
```

**응답**: `{ "ok": true, "expiresAt": "..." }`. 등록된 적 없는 기사가 좌표 없이 보내면 400 `{ "ok": false }`.

- `expiresAt`을 지금 + 60초로 늘린다. 기사 좌표가 오면 `presence:driver:{id}`와 `geo:drivers`의 위치를 바꾼다.
- **활성 호가의 `pickupDistanceKm`는 바꾸지 않는다** 🔄 v1.3. 픽업 거리는 호가 제출 시점 좌표로 고정된다.
- **클라이언트 전송 주기 권장: 20초** (TTL 60초의 1/3 — 두 번 실패해도 여유)

### 4.8 `GET /api/supply-demand` — 수급 조회 🔄 v1.3

**요청**: `?lat=12.97&lng=77.59`
**응답**: `{ "demand": 7, "supply": 3, "surge": 2.3, "radiusKm": 5.0 }`

| 필드 | 정의 |
|---|---|
| `demand` | 요청 좌표에서 반경 5km 안의 **온라인 승객 수**. 실제 사용자와 가상 접속 인구(§6.7)를 모두 센다. 거래를 만드는 승객은 생성 직전에 presence가 등록되므로 자기 자신도 포함된다 |
| `supply` | 반경 5km 안의 **ONLINE 기사 수**(`MATCHED` 제외). 가상 접속 인구 포함 |
| `surge` | `clamp(demand / max(supply, 1), 0.7, 3.0)`을 0.1 단위로 반올림 |
| `radiusKm` | 5.0 고정 |

- 반경 검색은 Redis `GEOSEARCH geo:riders` / `geo:drivers … BYRADIUS 5 km`로 한다.
- surge는 **실서비스 기준가에만** 쓴다. 논문의 모델 A 평가와 메커니즘 실험은 surge = 1로 고정한다(ML 설계 v5 §5.1).

---

## 5. WebSocket (STOMP)

### 5.1 연결

```
엔드포인트: /ws   (네이티브 WebSocket, SockJS 아님)
구독:
  /topic/deal/{dealId}        — 해당 거래의 모든 이벤트
  /user/queue/errors          — 내가 보낸 명령의 거부 이벤트 (v1.2)
  /topic/market/{geohash}     — 정의만 있음, v1.3 범위에서 미구현 (§5.4)
```

### 5.2 클라이언트 → 서버 🔄 v1.3

| 목적지 | 페이로드 | 검증 |
|---|---|---|
| `/app/deal/{dealId}/bid` | `{ driverId, price, driverLat, driverLng, version }` | R1, R2, R5, R8, R11, R13 |
| `/app/deal/{dealId}/bid/withdraw` | `{ driverId, version }` | R5, R11 |
| `/app/deal/{dealId}/offer` | `{ riderId, price, version }` | R1, R2, R8, R11 |
| `/app/deal/{dealId}/accept-bid` | `{ riderId, bidId, version }` | R3, R9, R10, R11 — **승객 지목 수락** |
| `/app/deal/{dealId}/accept-offer` | `{ driverId, version }` | R3, R6, R9, R10, R11 — **기사 선착 수락** |

> **수락 메시지가 두 종류**인 것이 이 설계의 핵심이다. 승객은 `bidId`를 지목하고, 기사는 승객 오퍼를 수락한다.
> **좌표 필드명은 저장 모델(§1.2)과 동일하게 `driverLat`/`driverLng`를 사용한다.**
> `version`을 생략(null)하면 버전 검사를 하지 않는다.

### 5.3 서버 → 클라이언트: `/topic/deal/{dealId}`

**`bid.placed` / `bid.updated`** (`bid.updated` = 이 거래에 이미 호가가 있던 기사의 새 호가)
```json
{
  "event": "bid.placed",
  "dealId": "D-7f3a9c",
  "bid": {
    "bidId": "B-002", "driverId": "DR017", "price": 215.0,
    "driverLat": 12.9720, "driverLng": 77.5951,
    "pickupDistanceKm": 0.3, "pickupEtaMin": 1.4,
    "createdAt": "2026-09-15T04:13:02Z"
  },
  "lowestBidPrice": 190.0,
  "bidderCount": 2,
  "pendingSide": "RIDER",
  "round": 3,
  "version": 7
}
```

**`bid.withdrawn`**
```json
{
  "event": "bid.withdrawn", "dealId": "...",
  "bidId": "B-002", "driverId": "DR017",
  "reason": "BY_DRIVER",
  "lowestBidPrice": 190.0, "bidderCount": 1,
  "round": 3,
  "version": 8
}
```
`reason`: `BY_DRIVER` | `DRIVER_MATCHED_ELSEWHERE` 🔄 v1.3 (`DRIVER_DISCONNECTED` 삭제)

> `round`가 증가하지 않는 점에 주의 — 철회는 라운드에 포함되지 않는다(R8).
> `bidderCount`는 이벤트에서는 **현재 활성 호가 수**다. `DealHistory.bidderCount`(한 번이라도 호가한 기사 수)와 다르다(§6.4).

**`offer.posted`**
```json
{ "event": "offer.posted", "dealId": "...", "price": 175.0,
  "expiresAt": "2026-09-15T04:13:32Z", "pendingSide": "DRIVER", "round": 4, "version": 9 }
```

**`offer.expired`**
```json
{ "event": "offer.expired", "dealId": "...", "pendingSide": "RIDER", "round": 4, "version": 10 }
```

**`deal.matched`**
```json
{
  "event": "deal.matched",
  "dealId": "D-7f3a9c",
  "driverId": "DR017",
  "finalPrice": 215.0,
  "matchPath": "RIDER_PICKED_BID",
  "pickupDistanceKm": 0.3,
  "pickupEtaMin": 1.4,
  "lowestBidPrice": 190.0,
  "chosenRank": 2,
  "matchedAt": "2026-09-15T04:13:40Z",
  "version": 11
}
```

> `matchPath`: `RIDER_PICKED_BID` | `DRIVER_TOOK_OFFER`
> `chosenRank`: §6.6 순위 규칙에서 몇 번째 호가가 선택됐는지 (1 = 최저가). 기사가 오퍼를 수락하면 0. **논문 분석의 핵심 필드**
> 기사가 오퍼를 수락했고 그 거래에 자기 호가가 없었으면 `pickupDistanceKm`·`pickupEtaMin`은 null이다. 호가가 하나도 없었으면 `lowestBidPrice`도 null이다.

**`deal.expired`**
```json
{ "event": "deal.expired", "dealId": "...", "reason": "TTL", "version": 12 }
```
`reason`: `TTL` | `ROUND_LIMIT` | `CANCELLED_BY_RIDER` 🔄 v1.3 (`RIDER_DISCONNECTED` 삭제)

**`error`** (요청자에게만 전송) — 구독 경로 `/user/queue/errors` (v1.2)
```json
{
  "event": "error",
  "dealId": "D-7f3a9c",
  "code": "PRICE_NOT_CONCEDED",
  "message": "직전 호가(215.0)보다 높은 가격은 제출할 수 없습니다",
  "version": 7
}
```

> **모든 이벤트가 `version` 필드명을 공유한다.** 클라이언트는 단일 파서로 `event`/`dealId`/`version`을 추출한 뒤 타입별 처리로 분기할 수 있다. 거래가 없으면 `version`은 0이다.

### 5.4 서버 → 클라이언트: `/topic/market/{geohash}` — 정의만 유지, v1.3 미구현

| 이벤트 | 페이로드 |
|---|---|
| `market.deal.created` | §4.4의 요약 객체 |
| `market.deal.updated` | `{ dealId, lowestBidPrice, riderOfferPrice, bidderCount, pendingSide, version }` |
| `market.deal.closed` | `{ dealId, reason, version }` |

> 이번 구현에서는 만들지 않는다. 기사 화면은 `GET /api/market`을 3초마다 부른다.

### 5.5 에러 코드 전체 (13종) 🔄 v1.3

| 코드 | 의미 | 구현 |
|---|---|---|
| `PRICE_NOT_CONCEDED` | R1 위반 — 자기 직전 호가보다 불리한 방향 | ✅ |
| `OUT_OF_BAND` | R2 위반 — 호가 밴드 이탈 | ✅ |
| `DEAL_ALREADY_MATCHED` | R9 — 이미 체결됨 | ✅ |
| `DEAL_NOT_ACTIVE` | 거래가 없거나, 종료 상태이거나, 만료 시각이 지남 | ✅ |
| `BID_NOT_FOUND` | 지목한 `bidId`가 없거나 철회됨, 또는 철회할 호가가 없음 | ✅ |
| `OFFER_NOT_FOUND` | 승객 오퍼가 없음 | ✅ |
| `OFFER_EXPIRED` | R6 — 오퍼 TTL 만료 | ✅ |
| `DRIVER_NOT_AVAILABLE` | R11 — 기사가 `MATCHED`이거나 ONLINE이 아님 | ✅ |
| `NOT_DEAL_OWNER` | 승객이 남의 거래에 행위 시도 | ✅ |
| `VERSION_CONFLICT` | `version` 불일치 → 클라이언트 재동기화 필요 | ✅ |
| `ROUND_LIMIT_EXCEEDED` | R8 | ✅ |
| `MAX_ACTIVE_BIDS_EXCEEDED` | R13 — 기사당 동시 활성 호가 50건 초과 🆕 v1.3 | ✅ |
| `RATE_LIMIT_EXCEEDED` | 기사당 분당 10회 초과 (R8 악용 방지) | 정의만 (미구현) |

### 5.6 `version` 규약

- **모든 서버 → 클라이언트 이벤트에 `version` 필드로 포함**한다 (에러 이벤트 포함)
- 거래 상태가 바뀔 때마다 1씩 증가한다. R10 자동 철회로 바뀐 다른 거래의 version도 1 증가한다.
- 클라이언트는 자기가 아는 version보다 **낮거나 같은** 이벤트를 무시한다
- 클라이언트는 요청 시 자기가 아는 version을 함께 보내고, Lua 스크립트가 같은지 검사한다
- `VERSION_CONFLICT`를 받으면 `GET /api/deals/{dealId}`로 재동기화한다

---

## 6. 구현 참고

### 6.1 Redis 키 스키마 🔄 v1.3

**공통 원칙**
- Redis **단일 인스턴스**를 쓴다(Cluster·Sentinel 미사용). 스크립트는 키 이름을 인자로 받지 않고 안에서 조립한다(단일 인스턴스에서만 허용되는 방식).
- **`EXPIRE`/`PEXPIRE`를 쓰지 않는다.** 시각은 모두 epoch 밀리초 정수로 저장하고, 만료·삭제는 ZSet 점수(시각)로 찾아 스윕이 처리한다.
- 실수(가격·좌표·거리)는 `string.format('%.17g', x)`로 저장한다(Lua 기본 `tostring`은 14자리라 값이 바뀐다).
- DB 번호: 실서비스 0, 실험 러너 14, JUnit 테스트 15.

| 키 | 타입 | 내용 |
|---|---|---|
| `deal:{dealId}` | Hash | 아래 "거래 필드" 표 |
| `deal:{dealId}:bids` | Hash | field=`driverId`, value=호가 JSON `{bidId, driverId, price, driverLat, driverLng, pickupDistanceKm, pickupEtaMin, createdAt, seq}` (기사당 1개 보장) |
| `deal:{dealId}:lastBid` | Hash | field=`driverId`, value=직전 호가 가격 (R1 검증용, 철회·종료 후에도 유지) |
| `driver:{driverId}:deals` | Set | 이 기사가 **현재 활성 호가를 가진** dealId 집합 (R10 일괄 철회, R13 `SCARD`) |
| `driver:{driverId}:state` | Hash | `status=MATCHED`, `dealId` (체결된 기사만 존재. 없으면 MATCHED 아님. 그 `dealId` 거래가 물리 삭제될 때 지운다) |
| `presence:driver:{id}` | Hash | `lat, lng, expiresAt` |
| `presence:rider:{id}` | Hash | `expiresAt, activeDealId` |
| `presence:expiry` | ZSet | member=`D:{id}` 또는 `R:{id}`, score=`expiresAt` |
| `geo:drivers` | GEO | ONLINE이고 MATCHED가 아닌 기사 위치 (supply) |
| `geo:riders` | GEO | 온라인 승객 위치 (demand). 승객 위치는 등록 시 받은 좌표, 거래를 만들면 그 출발지 |
| `geo:deals` | GEO | 활성 거래의 출발지 (`/api/market`) |
| `deals:expiry` | ZSet | 활성 거래, score=`expiresAt` (R7 스윕) |
| `offers:expiry` | ZSet | 살아 있는 오퍼가 있는 거래, score=`offerExpiresAt` (R6 스윕) |
| `deals:purge` | ZSet | 모든 거래, score=`purgeAt = createdAt + 300000` (물리 삭제) |

**거래 필드** (`deal:{dealId}` Hash)

| 묶음 | 필드 |
|---|---|
| 기본 | `dealId, riderId, originLat, originLng, basePrice, bandMin, bandMax, status, pendingSide, round, version, withdrawCount, nextBidSeq, createdAt, expiresAt, purgeAt` |
| 규칙 값 (생성 시 복사) | `offerTtlMs, roundLimit, avgSpeedKmh, detourFactor, maxActiveBids` — 실험 E4가 거래마다 다른 값을 쓸 수 있게 거래에 저장한다 |
| 오퍼 | `offerPrice, offerCreatedAt, offerExpiresAt` (없으면 필드 없음), `lastOfferPrice` (R1, 유지) |
| 종료 | `endReason` (`TTL`/`ROUND_LIMIT`/`CANCELLED_BY_RIDER`), `closedAt` |
| 체결 | `matchDriverId, finalPrice, matchPath, chosenRank, matchLowestBidPrice, winningPickupDistanceKm, winningPickupEtaMin, lowestBidPickupDistanceKm, lowestBidPickupEtaMin, matchedAt` |
| 부가 정보 | `meta` — JSON 문자열. 규칙이 읽지 않는 표시용 값(`destLat, destLng, distanceKm, durationMin, demand, supply, avgRainMm, weatherFactor, routePolyline, priceSource` 등). Java가 만들어 넘기고 그대로 돌려받는다 |

> 호가 순위는 `:bids` Hash의 값을 읽어 Lua `table.sort`로 (price, seq) 오름차순 정렬해 구한다. 가격은 실수 그대로 비교한다(정수 점수로 바꾸지 않는다). 정렬용 ZSet은 두지 않는다(v1.3).
> `lastBid`·`lastOfferPrice`는 철회되어도 지우지 않는다 — R1의 "철회로 제약을 리셋할 수 없음".
> 거래가 종료(체결·만료·취소)되면 같은 스크립트 안에서 `deals:expiry`·`offers:expiry`·`geo:deals`에서 빼고, 남은 호가를 낸 모든 기사의 `driver:{id}:deals`에서 그 거래를 뺀다(R13 건수 누수 방지).

### 6.2 픽업 거리·ETA 계산

기사 호가 제출 시 `place_bid.lua`가 계산한다. **ORS를 호출하지 않는다** (호가마다 API를 부르면 쿼터가 즉시 소진).

```
pickupDistanceKm = haversine(driverPos, dealOrigin)   // 지구 반지름 6371.0km
pickupEtaMin     = pickupDistanceKm / AVG_SPEED_KMH × 60 × DETOUR_FACTOR

AVG_SPEED_KMH  = 20   (방갈로르 도심 평균)
DETOUR_FACTOR  = 1.3  (직선거리 → 실도로 보정)
```

> Lua의 haversine은 Java `domain/Geo.haversineKm`과 **같은 식·같은 반지름·같은 연산 순서**여야 한다: `dLat = math.rad(lat2 − lat1)`, `dLng = math.rad(lng2 − lng1)`, `a = sin(dLat/2)² + cos(rad lat1)·cos(rad lat2)·sin(dLng/2)²`, `d = 2R·atan2(√a, √(1−a))`. JVM과 C 라이브러리의 sin/cos는 마지막 자리에서 다를 수 있으므로 테스트는 1e-9 허용 오차로 비교한다. 두 상수는 거래 필드(`avgSpeedKmh`, `detourFactor`)에서 읽는다.
> heartbeat는 이미 낸 호가의 픽업 거리를 바꾸지 않는다(v1.3).

### 6.3 정렬 옵션 (프론트)

승객 화면의 호가 목록은 세 가지 정렬을 제공한다.

| 정렬 | 기준 |
|---|---|
| 가격순 (기본) | `price` 오름차순 |
| 빨리 도착순 | `pickupEtaMin` 오름차순 |
| 추천순 | `price + TIME_VALUE × pickupEtaMin` 오름차순 |

`TIME_VALUE` = **2.0 ₹/min** (프론트 `app.js` 상수).

### 6.4 `DealHistory` 컬럼 🔄 v1.3

거래가 종료되면 그 종료를 일으킨 서버가 한 행을 기록한다(Lua 결과의 `closed` 목록, §6.6). **메커니즘 분석의 핵심 데이터**다.

```java
double finalPrice;                 // 체결가
double lowestBidPrice;             // 체결 시점 최저 호가
int    chosenRank;                 // 순위 규칙에서 몇 번째를 골랐나 (1 = 최저가, 0 = 기사가 오퍼 수락)
double winningPickupDistanceKm;    // 선택된 기사의 픽업 거리
double winningPickupEtaMin;
double lowestBidPickupDistanceKm;  // 최저가 기사의 픽업 거리 (비교군)
double lowestBidPickupEtaMin;
String matchPath;                  // RIDER_PICKED_BID | DRIVER_TOOK_OFFER
int    bidderCount;                // 이 거래에 한 번이라도 호가한 기사 수 (lastBid 크기)
int    roundCount;
int    withdrawCount;              // 자발적 철회 횟수 (R10 자동 철회는 제외)
long   negotiationDurationMs;
String endReason;                  // TTL | ROUND_LIMIT | CANCELLED_BY_RIDER  🔄 v1.3
String experimentTag;
Long   randomSeed;
```

### 6.5 스윕 (Sweeper) 🔄 v1.3

**1초마다** 스윕 스크립트 `sweep.lua`를 한 번 실행한다(`@Scheduled(fixedRate = 1000)`, `deal/ExpirySweeper`). 실험 러너는 1초마다가 아니라 **만료 시각마다** 같은 스크립트를 부른다(거래 `expiresAt`, 오퍼 `expiresAt`).

`sweep.lua`가 하는 일 (이 순서, 각 단계는 시각 오름차순 → 같으면 member 사전순)

| 단계 | 대상 | 동작 |
|---|---|---|
| 1 | `deals:expiry`에서 score ≤ nowMs | 거래 `EXPIRED`, `endReason=TTL`, 호가·오퍼 제거, version +1, `deal.expired(TTL)` |
| 2 | `offers:expiry`에서 score ≤ nowMs | 거래 상태가 `OPEN`/`NEGOTIATING`이고 오퍼가 있으면 오퍼 제거, `pendingSide=RIDER`, version +1, `offer.expired`. 어느 경우든 `offers:expiry`에서 뺀다 |
| 3 | `presence:expiry`에서 score ≤ nowMs | **참여 중(§1.5)이 아니면** presence와 GEO 위치 삭제. 참여 중이면 지우지 않고 `presence:expiry` 점수를 `nowMs + presenceTtlMs`로 미룬다(R5. 같은 사람을 매 스윕마다 다시 읽지 않게) |
| 4 | `deals:purge`에서 score ≤ nowMs | 아직 `OPEN`/`NEGOTIATING`이면 먼저 1단계와 같이 `EXPIRED(TTL)`로 닫는다(정리 누락 방지). `MATCHED` 거래면 승자의 `driver:{id}:state`가 이 거래를 가리킬 때 지우고, 그 기사의 presence가 살아 있으면 `geo:drivers`에 다시 넣는다(운행 완료 가정). 그다음 키 3개(`deal:{id}`, `:bids`, `:lastBid`)를 삭제 |

- `sweep.lua` ARGV: `nowMs`, `limit`(단계별 최대 처리 건수, 기본 1,000), `presenceTtlMs`(60,000). 남으면 다음 스윕이 이어서 한다.
- 스윕이 만든 이벤트도 **일반 이벤트와 똑같이 브로드캐스트**하고, 종료된 거래는 `DealHistory`에 기록한다.
- 서버가 여러 대면 각자 스윕을 돌려도 된다. 스크립트가 원자적이라 같은 전이는 한 번만 일어나고, 이벤트는 그 전이를 실행한 서버만 받는다.

**설계 판단 근거**

| 방식 | 채택 | 사유 |
|---|---|---|
| Redis `EXPIRE` + keyspace notification | ❌ | 가상 시계와 맞지 않음, 서버 설정 필요, 이벤트 유실 가능(at-most-once) |
| 명령마다 다른 거래까지 정리 | ❌ | 만료된 오퍼에 대한 수락이 `OFFER_EXPIRED` 대신 `OFFER_NOT_FOUND`로 바뀌어 규칙(R6) 의미가 달라진다 |
| **필드 시각 + 1초 스윕** | ✅ | 설정 불필요, 유실 없음, 실서비스·실험이 같은 스크립트, 재시작에도 안전 |

**부하 추정**: 스윕 1회 = `ZRANGEBYSCORE` 4회 + 처리 건수만큼의 쓰기. 활성 거래 100건 수준에서 무시할 만하다.

### 6.6 Lua 스크립트 계약 🆕 v1.3

**흥정 규칙의 유일한 구현은 `PartA/src/main/resources/redis/`의 Lua 스크립트다.** 실서비스(`DealService`)와 실험 러너(`experiment/`)는 같은 Java 게이트웨이 `redis/RedisMarket`을 통해 같은 스크립트를 부른다.

**파일**

| 스크립트 | 하는 일 | 규칙 |
|---|---|---|
| `lib/common.lua` | 모든 스크립트 앞에 붙는 공용 함수(숫자 형식, haversine, 거래 읽기, 순위 정렬, 이벤트 생성, 종료 정리, R10 정리, 기사 ONLINE 판정) | — |
| `create_deal.lua` | 거래 생성, 승객 presence 등록 | R4, R7 |
| `get_deal.lua` | 읽기 전용 스냅샷 | — |
| `place_bid.lua` | 호가 제출·갱신 | R1, R2, R5, R8, R11, R13 |
| `withdraw_bid.lua` | 호가 철회 | R5, R11 |
| `post_offer.lua` | 승객 오퍼 | R1, R2, R6, R8, R11 |
| `accept_bid.lua` | 승객 지목 수락 | R3, R9, R10 |
| `accept_offer.lua` | 기사 선착 수락 | R3, R6, R9, R10, R11 |
| `cancel_deal.lua` | 승객 취소 | R12 |
| `sweep.lua` | §6.5 | R5, R6, R7, 운행 완료 가정 |
| `presence_upsert.lua` | 등록·heartbeat (기사·승객) | R5, R11 |
| `presence_remove.lua` | 가상 인구의 접속 종료. 참여 중이면 아무것도 하지 않음 | R5 |

**호출 규약**
- `KEYS`는 비우고, `ARGV[1]`은 항상 `nowMs`(호출자의 시계, epoch 밀리초 정수)다. **스크립트 안에서 `redis.call('TIME')`과 `math.random`을 쓰지 않는다.**
- Java는 `SCRIPT LOAD`로 SHA를 받아 `EVALSHA`로 부르고, `NOSCRIPT`면 다시 로드한다. 로더는 `lib/common.lua`를 각 스크립트 앞에 이어 붙인다.
- 반환값은 JSON 문자열 하나다(`cjson.encode`).
  - 성공: `{"ok":true,"events":[{"dealId":…,"event":…,…}],"closed":["D-…"],"requesterError":null 또는 {"code","message","version"}}`
  - 거부: `{"ok":false,"code":"OUT_OF_BAND","message":"…","version":7}` — 거부면 아무 키도 바꾸지 않는다.
  - **라운드 상한(R8)은 거부가 아니다**: `ok:true`, `events:[deal.expired(ROUND_LIMIT)]`, `closed:[dealId]`, `requesterError:{code:"ROUND_LIMIT_EXCEEDED", version:<종료 뒤 version>}`. round는 20 그대로이고 호가·오퍼는 지워진다.
  - cjson은 빈 Lua 테이블을 `{}`로 쓰고 nil 필드는 아예 빠뜨린다. 값이 없음은 `cjson.null`로 넣고, Java 파서는 `{}`를 빈 목록으로, 빠진 필드를 null로 읽는다.
  - 종료 시각(`closedAt`)은 그 스크립트의 `nowMs`다. `DealHistory`도 이 값을 쓴다.
- JSON 안의 실수는 `'%.17g'` **문자열**로 넣는다(cjson은 14자리까지만 쓴다). 정수(version, round, bidderCount, chosenRank, 시각 ms)는 숫자로 넣는다. Java는 이를 `domain/DealEvent` 레코드로 바꿔 기존 `DealJson`으로 내보낸다(와이어 형식은 §5.3 그대로).
- **결정성**: `SMEMBERS`·`HGETALL` 결과를 순회할 때는 반드시 `table.sort`로 정렬한 뒤 순회한다. 같은 입력과 같은 `nowMs`면 같은 결과·같은 이벤트 순서가 나와야 한다(실험 러너의 바이트 재현 조건).

**명령 공통 검사 순서** (모든 명령 스크립트, 먼저 걸린 것 하나만 돌려준다)

1. 거래 키 없음 → `DEAL_NOT_ACTIVE`, version 0
2. 상태가 `MATCHED` → `DEAL_ALREADY_MATCHED` / `EXPIRED`·`CANCELLED` → `DEAL_NOT_ACTIVE`
3. `nowMs ≥ expiresAt` → `DEAL_NOT_ACTIVE` (상태는 바꾸지 않음. 전이는 스윕이 함)
4. 행위자: 승객 명령(오퍼·지목 수락·취소)인데 `riderId`가 다르거나 비어 있음 → `NOT_DEAL_OWNER` / 기사 명령(호가·철회·오퍼 수락)인데 `driverId`가 비어 있거나, ONLINE이 아니거나, MATCHED → `DRIVER_NOT_AVAILABLE`
5. `version`을 보냈고 현재와 다름 → `VERSION_CONFLICT` (취소는 검사하지 않음)
6. 명령별 검사·적용 (아래)

**명령별 검사·적용**

| 명령 | 검사 (순서대로) | 적용 |
|---|---|---|
| 호가 | `OUT_OF_BAND` → `PRICE_NOT_CONCEDED`(price > lastBid) → `MAX_ACTIVE_BIDS_EXCEEDED`(이 거래에 살아 있는 호가가 없고(`SISMEMBER` = 0) `SCARD ≥ maxActiveBids`) → round ≥ roundLimit이면 거래 `EXPIRED(ROUND_LIMIT)` + `requesterError=ROUND_LIMIT_EXCEEDED` | `bidId = "B-%03d"(nextBidSeq)`, 기존 호가 대체, lastBid 갱신, nextBidSeq +1, `NEGOTIATING`, `pendingSide=RIDER`, round +1, version +1, `SADD driver:{id}:deals`. 이벤트 `bid.updated`(이 거래에 살아 있던 호가를 대체) 또는 `bid.placed` |
| 철회 | 살아 있는 호가 없음 → `BID_NOT_FOUND` | 호가 제거, withdrawCount +1, version +1, `SREM`. `bid.withdrawn(BY_DRIVER)` |
| 오퍼 | `OUT_OF_BAND` → `PRICE_NOT_CONCEDED`(price < lastOfferPrice) → 라운드 상한(호가와 같음) | 오퍼 = (price, nowMs, nowMs + offerTtlMs), lastOfferPrice 갱신, `NEGOTIATING`, `pendingSide=DRIVER`, round +1, version +1, `offers:expiry` 갱신. `offer.posted` |
| 지목 수락 | `bidId`가 살아 있는 호가에 없음 → `BID_NOT_FOUND` | 순위 = 살아 있는 호가를 (가격, seq) 오름차순으로 `table.sort`. `chosenRank` = 지목 호가의 순위, 비교군 = 1위 호가. 체결(아래) |
| 오퍼 수락 | 오퍼 없음 → `OFFER_NOT_FOUND` → `nowMs ≥ offerExpiresAt` → `OFFER_EXPIRED` | `chosenRank = 0`, `finalPrice` = 오퍼 가격, 승자 픽업 = 그 기사의 이 거래 호가(없으면 null), 비교군 = 1위 호가(없으면 null). 체결(아래) |
| 취소 | (검사 없음) | `CANCELLED`, `endReason=CANCELLED_BY_RIDER`, 호가·오퍼 제거, version +1. `deal.expired(CANCELLED_BY_RIDER)` |

- **체결**: `MATCHED`, 오퍼 제거, 체결 필드 기록, version +1, `deal.matched`. 체결된 거래의 호가 목록은 스냅샷에 남긴다. 이어서 같은 스크립트에서 R10: 승자의 `driver:{id}:state = MATCHED`, `geo:drivers`에서 제거, `driver:{id}:deals`의 다른 거래(dealId 사전순)마다 상태가 `OPEN`/`NEGOTIATING`(만료 시각은 보지 않음)이고 그 기사 호가가 있으면 제거·version +1·`bid.withdrawn(DRIVER_MATCHED_ELSEWHERE)`(withdrawCount는 늘리지 않음), 마지막에 그 Set 삭제.
- **종료 정리**(체결·만료·취소 공통): §6.1의 마지막 인용 단락대로 인덱스에서 빼고, 거래 ID를 결과의 `closed`에 넣는다.
- **기사 ONLINE 판정**(R11): `driver:{id}:state`가 MATCHED면 불가. 아니면 `presence:driver:{id}.expiresAt > nowMs` 또는 `SCARD driver:{id}:deals > 0`이면 가능.

### 6.7 가상 접속 인구 (데모 전용) 🆕 v1.3

실서비스 화면의 수급(§4.8)을 현실적으로 채우기 위해, 서버가 가상의 사용자·기사를 접속시킨다. **논문 실험(모델 A, 메커니즘, 담합)에는 쓰지 않고, 논문에 실제 통계처럼 쓰지 않는다.**

| 항목 | 값 (`application.yml`의 `population.*`) |
|---|---|
| 인구 | 일반 사용자 1,000명(`SIM-U0000`~), 기사 200명(`SIM-D000`~) |
| 목표 동시 접속 비율 | **일반 사용자 5%, 기사 70%** (`SimulationBootstrap`·`SimulationEngine`의 기존 값) |
| 시작 시 | 무작위로 섞어 정확히 1,000 × 0.05 = 50명, 200 × 0.70 = 140명을 접속시킨다 |
| 1초마다 | 미접속자는 확률 `0.05 × 비율`로 접속, 접속자는 확률 `0.05 × (1 − 비율)`로 종료. 장기 평균이 목표 비율로 수렴한다(기존 `CHURN_INTENSITY = 0.05` 방식) |
| 위치 | 중심 (12.9716, 77.5946)에서 위도·경도 각각 ±0.1° 균등 무작위, 사람마다 고정 |
| presence | 접속 중인 가상 인원은 20초마다 heartbeat(`presence_upsert.lua`), 종료 시 `presence_remove.lua` |
| 행동 | **거래를 만들거나 호가하지 않는다.** `DealHistory`에 아무것도 쓰지 않는다. 수급 숫자에만 들어간다 |
| 난수 | `population.seed`(기본 42) |
| 켜고 끄기 | `population.enabled` — 기본 true(데모·파일럿), JUnit 테스트에서는 false. 실험 러너는 Spring을 띄우지 않으므로 해당 없음 |

> 참고: 이 값에서 반경 5km 안 수요/공급은 대략 8/22 ≈ 0.36이라 surge는 대부분 하한 0.7이 된다. 데모 화면용이므로 그대로 둔다. 바꾸려면 `population.user-count`만 바꾼다(비율 5%·70%는 유지).

---

## 7. v1.3이 계획 문서에 미치는 영향

| 항목 | 영향 | 계획 문서 |
|---|---|---|
| 규칙 구현 | Java 상태머신 → Lua 스크립트로 이관, 테스트도 Redis 위에서 | 리팩터링 계획 v6 카드 A2 |
| Presence·스윕 | 이탈 처리 삭제, presence 정리만 | 카드 A3 |
| 가상 접속 인구 | `SimulationEngine`·`SimulationBootstrap`을 지우고 `population/PopulationSimulator`로 대체 | 카드 A7 |
| 동시성 검증 | Redis 위에서 동시 수락 200회 × 2 + R13 동시 호가 | 카드 A6 |
| 실험 러너 | 같은 Lua 스크립트를 DB 14에서 호출, 에피소드마다 `FLUSHDB` | 카드 C1, ML 설계 v5 §6.1 |
| 논문 | 프로시딩 3.6을 "Redis Lua로 원자성 보장, 단일 서버로 실험"으로, 한계 절에 "참여 중 이탈 미고려" 추가 | ML 설계 v5 §8 |

---

## 8. 테스트 시나리오 (20종) 🔄 v1.3

모두 실제 Redis(DB 15) 위에서 Lua 스크립트를 직접 불러 확인한다(카드 A2·A3·A6).

| # | 시나리오 | 기대 |
|---|---|---|
| 1 | 정상 협상 → 승객이 최저가 수락 | MATCHED, `chosenRank=1` |
| 2 | **승객이 2번째로 싼 호가 수락** | MATCHED, `chosenRank=2` |
| 3 | 기사가 자기 호가를 올림 | `PRICE_NOT_CONCEDED` |
| 4 | 기사가 자기 호가를 내림 | 정상 접수, 이전 호가 대체(`bid.updated`, 새 `bidId`) |
| 5 | 기사 B가 기사 A보다 비싸게 호가 | **정상 접수** (전역 개선 불필요) |
| 6 | 승객이 오퍼를 내림 | `PRICE_NOT_CONCEDED` |
| 7 | 밴드 상한 초과 | `OUT_OF_BAND` |
| 8 | 밴드 하한 미달 | `OUT_OF_BAND` |
| 9 | 기사 2명이 동시에 승객 오퍼 수락 | 1건만 MATCHED, 나머지 `DEAL_ALREADY_MATCHED` |
| 10 | **승객 지목 수락과 기사 선착 수락 동시 발생** | 1건만 MATCHED |
| 11 | 승객 오퍼 TTL 만료 후(스윕 전) 기사 수락 시도 | `OFFER_EXPIRED` |
| 12 | 기사 이중 체결 차단 | 타 거래 호가 전부 철회, `reason=DRIVER_MATCHED_ELSEWHERE`, 이후 그 기사의 호가는 `DRIVER_NOT_AVAILABLE` |
| 13 | **참여 중인 기사**의 heartbeat가 60초 넘게 끊김 → 스윕 🔄 v1.3 | 호가 유지, 그 기사는 계속 호가·수락 가능 |
| 14 | 거래 TTL 만료 → 스윕 | EXPIRED(TTL) (활성 호가 있어도) |
| 15 | 라운드 20 도달 후 21번째 행위 | 행위 미반영, `ROUND_LIMIT_EXCEEDED`(요청자), 거래 EXPIRED(ROUND_LIMIT) |
| 16 | 승객 취소 | CANCELLED, 전 호가 철회 |
| 17 | **참여 중인 승객**의 heartbeat가 끊김 → 스윕 🔄 v1.3 | 거래 유지, 180초에 EXPIRED(TTL)로만 끝남 |
| 18 | **철회 후 재입찰** | 라운드 1만 증가(철회 미포함), R1은 직전 호가 기준 유지 |
| 19 | **기사가 50건에 호가한 상태에서 51번째 거래에 호가** 🆕 v1.3 | `MAX_ACTIVE_BIDS_EXCEEDED`, 50건 유지. 이미 호가한 거래의 가격 갱신은 정상 |
| 20 | **참여 중이 아닌 기사**의 heartbeat가 60초 넘게 끊김 → 스윕 → 호가 시도 🆕 v1.3 | presence 삭제, `DRIVER_NOT_AVAILABLE` |

---

## 9. 논문 관점 — 이 설계의 이점

`chosenRank`와 픽업 거리 기록으로 **새로운 분석이 가능해진다**. 단, "승객이 최저가를 고르는가"는 **사용자 파일럿(예비 관찰)으로만** 말하고, 시뮬레이션으로는 주장하지 않는다(ML 설계 v5 §8.2).

| 질문 | 지표 | 근거 데이터 |
|---|---|---|
| 승객은 항상 최저가를 고르는가? | `chosenRank == 1` 비율 | 파일럿 |
| 최저가를 포기할 때 무엇을 얻는가? | 평균 추가 지불액 vs 평균 ETA 단축 | 파일럿 |
| 시간 가치에 따라 선택이 어떻게 바뀌는가? | τ별 `chosenRank` 분포 | 시뮬레이션 E5 (프로토콜 반응만) |

---

## 10. 합의 체크리스트 🔄 v1.3

### 규칙
- [x] R1 행위자별 단조성 — 전역 가격 개선 폐기, 철회 후에도 직전 호가 제약 유지
- [x] R2 밴드 0.7~3.0배
- [x] R3 수락 권한 — 하드 턴 잠금 제거, 양측 상시 수락 가능
- [x] **R5 참여 중인 사용자는 오프라인으로 내리지 않음** (이탈 처리 없음, R7이 안전망)
- [x] R6 승객 오퍼 TTL 30초 / 응답 대기 알림 15초
- [x] R7 거래 TTL 180초, 물리 삭제 300초
- [x] R8 라운드 카운트 = 호가 제출 + 승객 오퍼만 (철회 제외), 상한 20. rate limit은 정의만
- [x] **R9·R10 원자성 = Redis Lua 스크립트 한 번**
- [x] **R13 기사당 동시 활성 호가 50건** (반복 횟수 상한, 복잡도 개선으로 주장하지 않음)

### 스키마 (2026-10-14까지 동결)
- [x] §4 REST 전 엔드포인트·필드 (`priceSource` 추가)
- [x] §5 WebSocket 전 메시지·필드
- [x] **모든 이벤트가 `version` 필드명 공유** (에러 포함)
- [x] **좌표 필드명 `driverLat`/`driverLng`로 통일** (요청·저장·이벤트 전부)
- [x] §5.5 에러 코드 13종 (`RATE_LIMIT_EXCEEDED`는 미구현)
- [x] §6.6 Lua 스크립트 계약

### 구현 결정
- [x] §6.1 Redis 단일 인스턴스, `EXPIRE` 미사용, 시각은 ms 정수, DB 0/14/15
- [x] §6.2 ETA 계산식 상수 (`AVG_SPEED_KMH=20`, `DETOUR_FACTOR=1.3`)
- [x] heartbeat 클라이언트 전송 주기 20초 / presence 60초
- [x] §6.4 `DealHistory` 컬럼 — 특히 `chosenRank`, `withdrawCount`, `endReason`
- [x] §6.5 스윕 주기 1초 (러너는 만료 시각마다)
- [x] §6.7 가상 접속 인구 5% / 70% (데모 전용)

### 검증
- [ ] §8 테스트 20종 (카드 A2·A3·A6)
