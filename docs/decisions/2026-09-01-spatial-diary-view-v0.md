---
status: adopted
decision: 76
adopted_at: 2026-09-01
---
# SpatialDiaryView v0는 기간·강수·낮밤으로 Capsule을 고르고 두 공간 metric으로 읽는다

결정 #74는 공간 일기장이 저장된 지도 한 장이 아니라 `Walk Selector → Field + Pin overlay`인
읽기 모델이라고 정했다. 결정 #75는 그 입력인 Capsule·Cellophane·TrailContext를 실제 DB에
봉인했다. 이번 결정은 Pin이 생기기 전에도 그 원판을 조건별 지도 배경으로 읽는 첫 제품 경로다.

## 범위

```text
POST /spatial-diary/views/query

Walk Selector
├─ dog_id
├─ since / until                   KST 달력 날짜, 양끝 포함
├─ precipitation = rain|dry|unknown
└─ daylight = day|night|unknown

Field
├─ visit_rate
└─ walk_utilization

Receipt
├─ total / selected / contributing Capsules
├─ context known / unknown
├─ paint_fp / normalization
└─ context / quality / claim policy version
```

`EntrySelector`는 비어 있어야 하고 `pin_count=0`이다. 지원하지 않는 entry filter나 metric을
무시하지 않고 422로 거부한다. PR4에서 Candidate·Attestation·Pin과 overlay를 연다.

## Context facet policy v1

Capsule에 저장된 원천값은 바꾸지 않는다. 다음 분류는 현재 읽기 정책이고 selector 지문에 정책
버전·임계값·달력 시간대를 함께 넣는다.

```text
precipitation_mm >= 0.1       rain
0 <= precipitation_mm < 0.1  dry
값 없음                       unknown

sun_elevation_deg >= 0        day
sun_elevation_deg < 0         night
값 없음                       unknown
```

snapshot status가 `unknown` 또는 `failed`면 두 축 모두 `unknown`이다. `partial`은 값이 있는
축만 분류하고 나머지 축은 `unknown`이다. 같은 축의 여러 값은 OR, 서로 다른 축과 기간은 AND다.
날짜는 `Asia/Seoul` 달력으로 해석한다. 이 정책은 `context_policy_version=1`이다.

실제 TrailContext provider는 아직 조립되지 않았으므로 현재 생성되는 Capsule은 기본적으로
`unknown`이다. v0가 unknown 필터와 무필터 cohort를 먼저 정확히 지원하는 이유다. 과거를 현재
날씨로 추정해 채우지 않는다.

## 두 Field의 분모

기존 `territory.spatial_stats`의 정의를 그대로 사용한다.

```text
visit_rate
  셀을 칠한 선택 산책 수 / 선택 Capsule 수
  빈 Cellophane도 "방문하지 않은 산책"으로 분모에 남는다.

walk_utilization
  각 산책의 셀 시간 질량을 먼저 합 1로 만든 뒤 기여 산책을 동등 가중
  빈 Cellophane은 정규화할 수 없어 contributing 분모에서만 빠진다.
```

quality policy v1의 이름은 `diary_v1`이다. v0에서는 산책을 cohort에서 제외하지 않으며,
`contributing`은 오직 선택한 field를 계산할 공간 재료가 있는지를 뜻한다. 품질 기반
judgeability는 Pin/Memory Place 질문이 생기는 후속 PR에서 MeasurementReceipt로 계산한다.

## Paint 세대와 결과 형태

선택된 Capsule의 `paint_fp`가 둘 이상이면 409로 실패한다. 서로 다른 격자·붓·sampling 결과를
같은 셀 좌표처럼 합치지 않는다. 선택 결과가 비었으면 결정 #75의 현재 canonical paint 세대를
영수증과 projection에 반환한다.

응답은 정렬된 `(q, r, value, numerator)`와 공통 denominator, 계산 projection을 반환한다.
보수적 연속 복원 Field나 화면 marker cluster를 저장하거나 통계에 재입력하지 않는다. 화면별
polygon·smoothing은 이 원 field를 소비하는 표현 책임이다.

manifest가 있는데 Cellophane 또는 TrailContext 자식이 없거나 paint 지문이 맞지 않으면 빈
지도로 숨기지 않고 서버 무결성 오류로 닫는다. 이 read path를 위한 새 영구 테이블이나 지도
snapshot은 만들지 않는다.

## 이 결정이 정하지 않는 것

- 실제 TrailContext provider
- Pin·Entry Selector·일기 문장
- ClaimAllowance와 품질 judgeability
- 보수적 연속 Field의 제품 렌더링
- 여러 paint 세대가 공존할 때의 세대 선택 UX
- 비교 View A/B와 Memory Place biography

## 다음 단계

PR4는 기존 `low_motion` observation에서 산책당 소수의 Candidate를 만들고, 실제 제시된 Offer와
사용자 Attestation을 거쳐 Episode Pin으로 승격한다. 이때 Entry Selector는 Pin overlay만 바꾸고
이번 PR의 Walk cohort와 공간 분모는 그대로 유지한다.
