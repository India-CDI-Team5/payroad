# PayRoad — 흥정 규칙 및 API 명세서 v1.1

> **상태**: 동결 후보 (팀원 합의 필요)
> **동결 범위**: §2 규칙과 §4~§5 스키마는 **W4 통합 전까지 변경 금지**
> **변경 시 절차**: 기존 필드는 유지하고 새 필드를 추가(어댑터 방식). 필드 삭제·이름 변경 금지

### v1.0 → v1.1 변경 이력

| # | 변경 | 위치 |
|---|---|---|
| 1 | 에러 이벤트 `currentVersion` → **`version`**으로 통일 | §5.3 |
| 2 | WebSocket 호가 요청 좌표를 **`driverLat`/`driverLng`**로 통일 | §5.2 |
| 3 | heartbeat 이탈 처리 방식을 **10초 주기 스윕 잡**으로 확정 | R5, §6.5 |
| 4 | **승객 heartbeat 이탈 처리** 신설 (v1.0 누락) | R5, §8 |
| 5 | R8 라운드 카운트에서 **철회 제외** 명시 | R8 |
| 6 | 테스트 시나리오 16종 → **18종** | §8 |

---

## 0. 설계 요약 — 무엇이 바뀌었나

기존 설계는 **"최저가 = 현재가"** 단일 가격 모델이었다. 승객이 픽업 거리를 고려해 더 비싼 기사를 선택할 수 있어야 하므로, **여러 호가가 동시에 살아있는 게시판 모델**로 변경한다.

| | 이전 설계 | 확정 설계 |
|---|---|---|
| 가격 표현 | `currentPrice` 단일값 | **활성 호가 목록** (기사당 1개) |
| 수락 대상 | 최저가 기사 자동 지정 | **승객이 호가를 지목해 수락** |
| 선택 기준 | 가격 단일 | **가격 + 픽업 거리/ETA** (승객 판단) |
| 턴 | 하드 잠금 (턴 소유자만 수락) | **응답 대기 표시** (UI 힌트 + 타임아웃 트리거) |
| 가격 개선 | 전역 강제 (현재가보다 유리해야) | **행위자별 단조성** (자기 호가만 양보 방향) |

**행위자별 단조성을 남긴 이유**: 전역 가격 개선을 버리면 협상이 발산할 수 있다. 각 참여자가 자기 호가를 양보 방향으로만 갱신하게 하면 **수렴성은 그대로 보장**되면서 가격 다양성은 살아난다.

---

## 1. 도메인 개념 정의

### 1.1 거래(Deal)

승객 1명의 특정 출발지 → 목적지 이동 요청. 시스템이 기준가를 붙여 시장에 게시한다.

### 1.2 기사 호가(DriverBid)

한 기사가 "이 가격이면 태우겠다"고 제시한 것. **기사당 최대 1개의 활성 호가**만 유지되며, 새 호가는 이전 호가를 대체한다.

```
{ bidId, driverId, price, driverLat, driverLng,
  pickupDistanceKm, pickupEtaMin, createdAt, version }
```

`pickupDistanceKm`와 `pickupEtaMin`은 서버가 계산한다(§6.2).

### 1.3 승객 오퍼(RiderOffer)

승객이 "이 가격이면 타겠다"고 전체 기사에게 공개 제시한 것. **거래당 최대 1개**만 존재하며, 새 오퍼가 이전 것을 대체한다.

```
{ price, createdAt, expiresAt }
```

### 1.4 체결 경로 (2가지)

| 경로 | 행위 | 결과 |
|---|---|---|
| **A. 승객 지목 수락** | 승객이 특정 기사의 호가를 선택 | 그 기사와 그 가격으로 체결 |
| **B. 기사 선착 수락** | 기사가 승객 오퍼를 수락 | 먼저 누른 기사와 오퍼 가격으로 체결 |

두 경로가 동시에 발생할 수 있으므로 원자적 단일 체결이 필수다(R9).

---

## 2. 흥정 규칙 R1~R12

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
| 거래 생성 직후 | `DRIVER` |

### R5. 활성 호가 관리 및 이탈 처리 🔄 v1.1

**호가 관리**
- 기사당 활성 호가 1개. 새 호가는 이전 것을 **대체**(replace)
- 기사가 호가를 철회(`WITHDRAW`)하면 목록에서 제거

**이탈 처리 — 10초 주기 스윕 잡으로 수행**

| 대상 | 이탈 판정 | 동작 |
|---|---|---|
| **기사** | `presence:driver:{id}` 키 부재 (heartbeat 60초 끊김) | 그 기사의 **모든 활성 호가 철회**, `bid.withdrawn` 브로드캐스트 |
| **승객** | `presence:rider:{id}` 키 부재 (heartbeat 60초 끊김) | 해당 거래 **`CANCELLED`**, 전 호가 철회, `deal.expired(reason=RIDER_DISCONNECTED)` 브로드캐스트 |

> **구현 방식 확정**: Redis TTL은 키를 지울 뿐 애플리케이션 로직을 실행하지 않는다. keyspace notification은 별도 서버 설정(`notify-keyspace-events`)이 필요하고 이벤트 유실 가능성이 있어 채택하지 않는다. **`@Scheduled(fixedRate = 10000)` 스윕 잡**으로 활성 거래를 순회하며 presence 키 존재 여부를 확인한다. 최대 10초 지연이 발생하나 본 도메인에서는 허용 범위다. (§6.5)

### R6. 타임아웃

| 대상 | 값 | 만료 시 동작 |
|---|---|---|
| 승객 오퍼 TTL | **30초** | 오퍼 소멸, `pendingSide = RIDER`로 전환 |
| 응답 대기 알림 | **15초** | UI 카운트다운 종료. 거래는 유지, 상태 변화 없음 |

> 승객 오퍼에 별도 TTL을 둔 이유: 승객이 잊고 방치한 오퍼를 기사가 뒤늦게 수락하는 상황 차단

### R7. 거래 TTL

**180초**. 만료 시 `EXPIRED`. 활성 호가가 있어도 만료된다.

> Redis 키(`deal:{dealId}` 계열)의 실제 TTL은 300초다(§6.1). 논리적 만료(180초)와 물리적 삭제(300초) 사이 **120초 grace period**를 둬서, 만료 직후 도착한 `GET /api/deals/{dealId}` 요청이나 지연된 클라이언트가 마지막 상태(`EXPIRED`)를 여전히 조회할 수 있게 한다. `status` 필드는 180초 시점에 이미 `EXPIRED`로 갱신되므로 grace period 동안에도 활성 거래로 오인되지 않는다.

### R8. 라운드 상한 🔄 v1.1

**20회** 초과 시 `EXPIRED`.

**카운트 대상**
- ✅ 기사 호가 제출 (갱신 포함, 각각 1회)
- ✅ 승객 오퍼 게시 (갱신 포함, 각각 1회)

**카운트 제외**
- ❌ **호가 철회 (`WITHDRAW`)**
- ❌ 이탈로 인한 자동 철회
- ❌ 승객 오퍼 TTL 만료

> **근거**: 라운드 상한의 목적은 무한 협상 방지다. 철회는 협상을 진전시키는 행위가 아니라 이탈이며, 이를 카운트하면 실수로 철회 후 재입찰한 성실한 참여자가 불이익을 받는다. 철회-재입찰 반복 악용은 라운드가 아니라 **rate limit**(기사당 분당 10회)으로 제어한다.

### R9. 단일 체결 (원자성)

동시에 여러 수락이 들어와도 **정확히 1건만** 성공한다. 실패한 쪽은 `DEAL_ALREADY_MATCHED`.

적용 대상:
- 기사 2명이 동시에 승객 오퍼 수락
- 승객 지목 수락과 기사 선착 수락이 동시 발생

Redis Lua 스크립트 + `version` CAS로 보장한다.

### R10. 기사 이중 체결 차단

한 기사가 여러 거래에 호가를 낼 수 있다. 어느 한 거래가 체결되면 **그 기사의 다른 모든 활성 호가를 원자적으로 철회**하고, 상태를 `MATCHED`로 전환한다.

### R11. 참여 자격

- 기사 상태가 `ONLINE`일 때만 호가 제출 가능 (`MATCHED` 상태는 불가)
- 승객은 자신의 거래에만 오퍼 게시 가능
- 거래 상태가 `OPEN` 또는 `NEGOTIATING`일 때만 모든 행위 허용

### R12. 승객 취소

승객은 체결 전까지 언제든 취소 가능 → `CANCELLED`. 모든 활성 호가 철회.

---

## 3. 상태 전이

```
                      ┌─── 호가 없이 TTL 만료 ───┐
                      │                          ▼
[거래 생성] ──► OPEN ──첫 호가/오퍼──► NEGOTIATING ──수락──► MATCHED
                      │                    │  ▲                 
                      │                    └──┘   EXPIRED ◄── TTL/라운드 초과
                      │              호가·오퍼 반복
                      └── 승객 취소 / 승객 이탈 ──► CANCELLED
```

| 상태 | 의미 | 허용 행위 |
|---|---|---|
| `OPEN` | 게시됨, 아직 호가 없음 | 기사 호가, 승객 오퍼, 승객 취소 |
| `NEGOTIATING` | 호가/오퍼 존재 | 호가 갱신·철회, 오퍼 갱신, 양측 수락, 승객 취소 |
| `MATCHED` | 체결 완료 | 없음 (종료) |
| `EXPIRED` | 시간·라운드 초과 | 없음 (종료) |
| `CANCELLED` | 승객 취소 또는 승객 이탈 | 없음 (종료) |

---

## 4. REST API

### 4.1 `POST /api/deals` — 거래 생성

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
  "routePolyline": "encoded_polyline_string",
  "pendingSide": "DRIVER",
  "round": 0,
  "version": 1,
  "createdAt": "2026-09-15T04:12:33Z",
  "expiresAt": "2026-09-15T04:15:33Z"
}
```

> 생성 시 `deals:active`에 `dealId`를 추가한다(§6.1, §6.5 스윕 대상).

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

> `bids` 배열은 **가격 오름차순** 기본 정렬. 클라이언트가 `pickupEtaMin` 기준으로 재정렬할 수 있도록 두 값을 모두 내려준다.

### 4.3 `DELETE /api/deals/{dealId}` — 승객 취소

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

> 좌표는 100m 격자로 라운딩(프라이버시). `cells`는 클라이언트가 구독해야 할 Geohash 셀 목록.

### 4.5 `POST /api/presence/driver` — 기사 온라인 등록

**요청**: `{ "driverId": "DR042", "driverLat": 12.97, "driverLng": 77.59 }`
**응답**: `{ "driverId": "DR042", "status": "ONLINE", "expiresAt": "..." }`

### 4.6 `POST /api/presence/rider` — 승객 온라인 등록 🆕 v1.1

**요청**: `{ "riderId": "R001" }`
**응답**: `{ "riderId": "R001", "status": "ONLINE", "expiresAt": "..." }`

> 거래 생성 시 자동으로 등록되지만, 명시적 등록 엔드포인트도 제공한다(재접속 시).

### 4.7 `POST /api/presence/heartbeat` — 생존 신호

**요청**
```json
{ "actorId": "DR042", "actorType": "DRIVER", "driverLat": 12.97, "driverLng": 77.59 }
```
승객의 경우 좌표는 생략 가능:
```json
{ "actorId": "R001", "actorType": "RIDER" }
```

**응답**: `{ "ok": true, "expiresAt": "..." }`

> 기사는 위치를 함께 보내 활성 호가의 `pickupDistanceKm`를 갱신한다.
> **클라이언트 전송 주기 권장: 20초** (TTL 60초의 1/3 — 두 번 실패해도 여유)

### 4.8 `GET /api/supply-demand` — 수급 조회

**요청**: `?lat=12.97&lng=77.59`
**응답**: `{ "demand": 7, "supply": 3, "surge": 2.3, "radiusKm": 5.0 }`

---

## 5. WebSocket (STOMP)

### 5.1 연결

```
엔드포인트: /ws
구독:
  /topic/deal/{dealId}        — 해당 거래의 모든 이벤트
  /topic/market/{geohash}     — 셀 단위 시장 이벤트
```

### 5.2 클라이언트 → 서버 🔄 v1.1

| 목적지 | 페이로드 | 검증 |
|---|---|---|
| `/app/deal/{dealId}/bid` | `{ driverId, price, driverLat, driverLng, version }` | R1, R2, R5, R11 |
| `/app/deal/{dealId}/bid/withdraw` | `{ driverId, version }` | R5, R11 |
| `/app/deal/{dealId}/offer` | `{ riderId, price, version }` | R1, R2, R11 |
| `/app/deal/{dealId}/accept-bid` | `{ riderId, bidId, version }` | R3, R9 — **승객 지목 수락** |
| `/app/deal/{dealId}/accept-offer` | `{ driverId, version }` | R3, R6, R9, R11 — **기사 선착 수락** |

> **수락 메시지가 두 종류**인 것이 이번 설계의 핵심이다. 승객은 `bidId`를 지목하고, 기사는 승객 오퍼를 수락한다.
> **좌표 필드명은 저장 모델(§1.2)과 동일하게 `driverLat`/`driverLng`를 사용한다.**

### 5.3 서버 → 클라이언트: `/topic/deal/{dealId}`

**`bid.placed` / `bid.updated`**
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
`reason`: `BY_DRIVER` | `DRIVER_DISCONNECTED` | `DRIVER_MATCHED_ELSEWHERE`

> `round`가 증가하지 않는 점에 주의 — 철회는 라운드에 포함되지 않는다(R8).

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
> `chosenRank`: 가격 오름차순에서 몇 번째 호가가 선택됐는지 (1 = 최저가). **논문 분석의 핵심 필드**

**`deal.expired`**
```json
{ "event": "deal.expired", "dealId": "...", "reason": "TTL", "version": 12 }
```
`reason`: `TTL` | `ROUND_LIMIT` | `CANCELLED_BY_RIDER` | `RIDER_DISCONNECTED`

**`error`** (요청자에게만 전송) 🔄 v1.1
```json
{
  "event": "error",
  "dealId": "D-7f3a9c",
  "code": "PRICE_NOT_CONCEDED",
  "message": "직전 호가(215.0)보다 높은 가격은 제출할 수 없습니다",
  "version": 7
}
```

> **모든 이벤트가 `version` 필드명을 공유한다.** 클라이언트는 단일 파서로 `event`/`dealId`/`version`을 추출한 뒤 타입별 처리로 분기할 수 있다.

### 5.4 서버 → 클라이언트: `/topic/market/{geohash}`

| 이벤트 | 페이로드 |
|---|---|
| `market.deal.created` | §4.4의 요약 객체 |
| `market.deal.updated` | `{ dealId, lowestBidPrice, riderOfferPrice, bidderCount, pendingSide, version }` |
| `market.deal.closed` | `{ dealId, reason, version }` |

> 시장 이벤트에는 `routePolyline`·개별 호가 목록을 포함하지 않는다(페이로드 절감).

### 5.5 에러 코드 전체

| 코드 | 의미 |
|---|---|
| `PRICE_NOT_CONCEDED` | R1 위반 — 자기 직전 호가보다 불리한 방향 |
| `OUT_OF_BAND` | R2 위반 — 호가 밴드 이탈 |
| `DEAL_ALREADY_MATCHED` | R9 — 이미 체결됨 |
| `DEAL_NOT_ACTIVE` | 거래가 종료 상태 |
| `BID_NOT_FOUND` | 지목한 `bidId`가 없거나 철회됨 |
| `OFFER_NOT_FOUND` | 승객 오퍼가 없거나 만료 |
| `OFFER_EXPIRED` | R6 — 오퍼 TTL 만료 |
| `DRIVER_NOT_AVAILABLE` | R11 — 기사가 `MATCHED` 상태 또는 presence 없음 |
| `NOT_DEAL_OWNER` | 승객이 남의 거래에 오퍼 시도 |
| `VERSION_CONFLICT` | `version` 불일치 → 클라이언트 재동기화 필요 |
| `ROUND_LIMIT_EXCEEDED` | R8 |
| `RATE_LIMIT_EXCEEDED` | 기사당 분당 10회 초과 (R8 악용 방지) 🆕 v1.1 |

### 5.6 `version` 규약

- **모든 서버 → 클라이언트 이벤트에 `version` 필드로 포함**한다 (에러 이벤트 포함)
- 거래 상태가 바뀔 때마다 1씩 증가
- 클라이언트는 자기가 아는 version보다 **낮거나 같은** 이벤트를 무시한다
- 클라이언트는 요청 시 자기가 아는 version을 함께 보내고, 서버는 CAS 검증에 사용한다
- `VERSION_CONFLICT`를 받으면 `GET /api/deals/{dealId}`로 재동기화한다

---

## 6. 구현 참고

### 6.1 Redis 키 스키마 🔄 v1.1

| 키 | 타입 | 내용 | TTL |
|---|---|---|---|
| `deal:{dealId}` | Hash | `status, riderId, origin*, dest*, geohash, distanceKm, avgRainMm, weatherFactor, basePrice, bandMin, bandMax, riderOfferPrice, riderOfferExpiresAt, lowestBidPrice, bidderCount, pendingSide, round, version, createdAt, expiresAt` | 300s |
| `deal:{dealId}:bids` | Hash | field=`driverId`, value=호가 JSON (기사당 1개 보장) | 300s |
| `deal:{dealId}:bidsByPrice` | ZSet | score=price, member=`driverId` (정렬 조회용) | 300s |
| `deal:{dealId}:lastBid` | Hash | field=`driverId`, value=직전 호가 가격 (R1 검증용, 철회 후에도 유지) | 300s |
| `driver:{driverId}:deals` | Set | 이 기사가 호가를 낸 dealId 집합 (R10 일괄 철회용) | — |
| `presence:driver:{id}` | Hash | `status, driverLat, driverLng, lastHeartbeat` | **60s** |
| `presence:rider:{id}` | Hash | `status, lastHeartbeat, activeDealId` 🆕 | **60s** |
| `deals:active` | Set | 스윕 잡이 순회할 활성 dealId 집합. **`POST /api/deals` 생성 시 추가**, `MATCHED`/`EXPIRED`/`CANCELLED` 전이 시 제거 🆕 | — |
| `market:cell:{geohash}` | ZSet | score=createdAt, member=dealId | — |
| `geo:deals` / `geo:drivers` | GEO | 좌표 인덱스 | — |
| `ratelimit:driver:{id}` | String | 분당 호가 카운터 🆕 | 60s |

> `bids`(Hash)와 `bidsByPrice`(ZSet)를 **같은 Lua 스크립트 안에서 함께 갱신**해야 정합성이 유지된다.
> `lastBid`는 철회되어도 삭제하지 않는다 — R1의 "철회로 제약을 리셋할 수 없음"을 보장하기 위함.
> `deal:{dealId}` 계열 키의 TTL(300s)은 논리적 거래 TTL(180s, R7)보다 120초 길다 — grace period 근거는 R7 참조.
> `deals:active`는 거래 생성·종료 시점에 갱신되며, 상태 전이를 처리하는 동일 트랜잭션/Lua 스크립트 안에서 추가·제거해야 한다(누락 시 신규 거래가 스윕 대상에서 빠지거나 종료된 거래가 계속 순회됨).

### 6.2 픽업 거리·ETA 계산

기사 호가 제출 시 서버가 계산한다. **ORS를 호출하지 않는다** (호가마다 API를 때리면 쿼터가 즉시 소진).

```
pickupDistanceKm = haversine(driverPos, dealOrigin)
pickupEtaMin     = pickupDistanceKm / AVG_SPEED_KMH × 60 × DETOUR_FACTOR

AVG_SPEED_KMH  = 20   (방갈로르 도심 평균, 설정 외부화)
DETOUR_FACTOR  = 1.3  (직선거리 → 실도로 보정)
```

> **주의**: 리팩터링 계획에서 `Location.java`를 삭제하기로 했으나, Haversine 계산은 여기서 필요하다. **`GeoUtil.haversine(lat1, lng1, lat2, lng2)` 정적 유틸로 이관**할 것.

### 6.3 정렬 옵션 (프론트)

승객 화면의 호가 목록은 세 가지 정렬을 제공한다.

| 정렬 | 기준 |
|---|---|
| 가격순 (기본) | `price` 오름차순 |
| 빨리 도착순 | `pickupEtaMin` 오름차순 |
| 추천순 | `price + TIME_VALUE × pickupEtaMin` 오름차순 |

`TIME_VALUE`(₹/min)는 설정값. 기본값은 기준가·평균 ETA를 고려해 경험적으로 정한다.

### 6.4 `DealHistory` 추가 컬럼

기존 계획에 더해 아래를 반드시 기록한다 — **메커니즘 분석의 핵심 데이터**다.

```java
double finalPrice;                 // 체결가
double lowestBidPrice;             // 체결 시점 최저 호가
int    chosenRank;                 // 가격순 몇 번째를 골랐나 (1 = 최저가)
double winningPickupDistanceKm;    // 선택된 기사의 픽업 거리
double winningPickupEtaMin;
double lowestBidPickupDistanceKm;  // 최저가 기사의 픽업 거리 (비교군)
double lowestBidPickupEtaMin;
String matchPath;                  // RIDER_PICKED_BID | DRIVER_TOOK_OFFER
int    bidderCount, roundCount;
int    withdrawCount;              // 철회 횟수 (라운드와 별도 집계) 🆕
long   negotiationDurationMs;
String endReason;                  // TTL | ROUND_LIMIT | CANCELLED_BY_RIDER | RIDER_DISCONNECTED 🆕
String experimentTag;
Long   randomSeed;
```

### 6.5 이탈 스윕 잡 (Presence Sweeper) 🆕 v1.1

```java
@Scheduled(fixedRate = 10_000)   // 10초 주기
public void sweepDisconnected() {
    for (String dealId : redis.opsForSet().members("deals:active")) {
        DealSnapshot deal = loadDeal(dealId);
        if (deal == null || deal.isTerminal()) {
            redis.opsForSet().remove("deals:active", dealId);
            continue;
        }

        // 1) 승객 이탈 확인 → 거래 취소
        if (!redis.hasKey("presence:rider:" + deal.riderId())) {
            cancelDeal(dealId, "RIDER_DISCONNECTED");
            continue;
        }

        // 2) 기사 이탈 확인 → 해당 호가만 철회
        for (String driverId : deal.bidderIds()) {
            if (!redis.hasKey("presence:driver:" + driverId)) {
                withdrawBid(dealId, driverId, "DRIVER_DISCONNECTED");
            }
        }
    }
}
```

**설계 판단 근거**

| 방식 | 채택 | 사유 |
|---|---|---|
| Redis keyspace notification | ❌ | 서버 설정(`notify-keyspace-events`) 필요, 이벤트 유실 가능(at-most-once), 디버깅 난이도 |
| **10초 주기 스윕 잡** | ✅ | 설정 불필요, 유실 없음, 재시작에도 안전. 최대 10초 지연은 허용 범위 |

**부하 추정**: 활성 거래 100건 × 평균 호가 5개 = 500회 `EXISTS` / 10초 = 초당 50회. Redis에 무시할 수준.

> 스윕 잡이 수행하는 철회·취소도 **일반 이벤트와 동일하게 브로드캐스트**해야 한다. 그렇지 않으면 클라이언트 화면에 유령 호가가 남는다.

---

## 7. 이번 변경이 기존 계획에 미치는 영향

| 항목 | 영향 |
|---|---|
| R1~R5 | **전면 재작성** (본 문서가 최신) |
| W2 JUnit 테스트 | 12종 → **18종** (§8) |
| Lua 스크립트 | `place_bid.lua`가 Hash+ZSet+lastBid 동시 갱신. `accept_bid.lua`와 `accept_offer.lua`로 **분리** |
| `Location.java` 삭제 | **철회** → `GeoUtil.haversine()`로 이관 (§6.2) |
| 스윕 잡 | **신규 작업** — `PresenceSweeper` 클래스. W3 `PresenceService` 작업에 포함 |
| 프론트 협상 패널 | 단일 가격 → **호가 목록 + 정렬 토글** (작업량 증가) |
| D5 (체결 기준) | "가격 단일" → **"승객 선택, 가격·ETA 병기"** |
| 논문 | **Figure 1개 추가 가능** (§9) |

---

## 8. 테스트 시나리오 (W2, 18종) 🔄 v1.1

| # | 시나리오 | 기대 |
|---|---|---|
| 1 | 정상 협상 → 승객이 최저가 수락 | MATCHED, `chosenRank=1` |
| 2 | **승객이 2번째로 싼 호가 수락** | MATCHED, `chosenRank=2` |
| 3 | 기사가 자기 호가를 올림 | `PRICE_NOT_CONCEDED` |
| 4 | 기사가 자기 호가를 내림 | 정상 접수, 이전 호가 대체 |
| 5 | 기사 B가 기사 A보다 비싸게 호가 | **정상 접수** (전역 개선 불필요) |
| 6 | 승객이 오퍼를 내림 | `PRICE_NOT_CONCEDED` |
| 7 | 밴드 상한 초과 | `OUT_OF_BAND` |
| 8 | 밴드 하한 미달 | `OUT_OF_BAND` |
| 9 | 기사 2명이 동시에 승객 오퍼 수락 | 1건만 MATCHED, 나머지 `DEAL_ALREADY_MATCHED` |
| 10 | **승객 지목 수락과 기사 선착 수락 동시 발생** | 1건만 MATCHED |
| 11 | 승객 오퍼 TTL 만료 후 기사 수락 시도 | `OFFER_EXPIRED` |
| 12 | 기사 이중 체결 차단 | 타 거래 호가 전부 철회, `reason=DRIVER_MATCHED_ELSEWHERE` |
| 13 | 기사 heartbeat 끊김 → 스윕 잡 실행 | 해당 호가 자동 철회, `reason=DRIVER_DISCONNECTED` |
| 14 | 거래 TTL 만료 | EXPIRED (활성 호가 있어도) |
| 15 | 라운드 20 초과 | `ROUND_LIMIT_EXCEEDED` → EXPIRED |
| 16 | 승객 취소 | CANCELLED, 전 호가 철회 |
| 17 | **승객 heartbeat 끊김 → 스윕 잡 실행** 🆕 | CANCELLED, `reason=RIDER_DISCONNECTED`, 전 호가 철회 |
| 18 | **철회 후 재입찰** 🆕 | 라운드 1만 증가(철회 미포함), R1은 직전 호가 기준 유지 |

---

## 9. 논문 관점 — 이번 변경의 이점

`chosenRank`와 픽업 거리 기록으로 **새로운 분석이 가능해진다**.

**추가 실험 (W4)**

| 질문 | 지표 |
|---|---|
| 승객은 항상 최저가를 고르는가? | `chosenRank == 1` 비율 |
| 최저가를 포기할 때 무엇을 얻는가? | 평균 추가 지불액 vs 평균 ETA 단축 |
| 기사 수가 늘면 선택 패턴이 바뀌는가? | `bidderCount` 구간별 `chosenRank` 분포 |
| 악천후에서 시간 가치가 올라가는가? | 강수 유무별 추가 지불 의향 비교 |

**예상되는 결론 형태**

> "승객은 최저가 호가를 N% 비율로 선택했으며, 최저가를 포기한 경우 평균 X원을 추가 지불하고 Y분의 대기 시간을 단축했다. 이는 가격 단일 기준 매칭이 승객 효용을 과소평가함을 시사한다."

단순 가격 경쟁보다 **훨씬 흥미로운 메커니즘 발견**이며, Figure 1개가 추가로 확보된다.

---

## 10. 합의 체크리스트 🔄 v1.1

### 규칙
- [ ] R1 행위자별 단조성 — 전역 가격 개선 폐기에 동의
- [ ] R1 철회 후 재입찰 시에도 직전 호가 제약 유지 (`lastBid` 미삭제)
- [ ] R2 밴드 0.7~3.0배
- [ ] R3 수락 권한 — 하드 턴 잠금 제거, 양측 상시 수락 가능
- [ ] **R5 이탈 처리 = 10초 주기 스윕 잡** (keyspace notification 미채택)
- [ ] **R5 승객 heartbeat 이탈 → 거래 CANCELLED**
- [ ] R6 승객 오퍼 TTL 30초 / 응답 대기 알림 15초
- [ ] R7 거래 TTL 180초
- [ ] **R8 라운드 카운트 = 호가 제출 + 승객 오퍼만 (철회 제외)**, 상한 20
- [ ] R8 악용 방지 = 기사당 분당 10회 rate limit

### 스키마 (W4까지 동결)
- [ ] §4 REST 전 엔드포인트·필드
- [ ] §5 WebSocket 전 메시지·필드
- [ ] **모든 이벤트가 `version` 필드명 공유** (에러 포함)
- [ ] **좌표 필드명 `driverLat`/`driverLng`로 통일** (요청·저장·이벤트 전부)
- [ ] §5.5 에러 코드 12종

### 구현 결정
- [ ] §6.2 ETA 계산식 상수 (`AVG_SPEED_KMH=20`, `DETOUR_FACTOR=1.3`)
- [ ] heartbeat 클라이언트 전송 주기 20초 / TTL 60초
- [ ] §6.4 `DealHistory` 컬럼 — 특히 `chosenRank`, `withdrawCount`, `endReason`
- [ ] §6.5 스윕 잡 주기 10초

### 검증
- [ ] §8 테스트 18종
