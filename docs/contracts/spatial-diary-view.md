# Spatial Diary View 질의 계약 v1

공간 일기장은 저장된 지도 한 장이 아니다. 산책별 Capsule과 Cellophane, 사용자 Episode Pin을
현재 조건으로 고르고 통계·표현으로 조립한 읽기 결과다.

```text
SpatialDiaryViewSpec
→ query
→ SpatialDiaryViewResult + SpatialDiaryViewReceipt
```

즐겨찾기는 Result가 아니라 Spec을 저장한다. 새 산책이 생기면 같은 Spec의 결과는 자연스럽게
업데이트된다. 특정 시점의 회고나 공유를 동결하는 Snapshot은 v1 범위 밖이다.

## ViewSpec

```text
SpatialDiaryViewSpec
├─ WalkSelector
│  ├─ dog_id
│  ├─ since / until
│  └─ ContextFacetFilter[]
├─ EntrySelector
│  ├─ subject_roles
│  └─ meaning_codes
├─ field_metric
└─ QualityPolicy
```

### Walk Selector

공간 배경과 장소 노출의 cohort를 고른다. 모든 facet은 AND다. facet은 동결된 context 원자에서
`policy_version`으로 파생하며 `unknown`을 명시적으로 포함하거나 제외한다.

### Entry Selector

선택된 cohort 안에서 Pin overlay만 고른다. Entry 조건이 있는 산책만 Walk cohort에 남기지 않는다.

```text
비 오는 가을 저녁 산책 9회  → 배경과 분모 9
그 안의 탐색 Pin 4개          → overlay 4
```

### Quality Policy

품질은 Walk Selector가 아니다. 선택 산책을 조용히 빼지 않고 질문마다 contributing·judgeable·
unjudgeable을 가른다. 정책은 MeasurementReceipt를 읽고 버전을 결과 영수증에 남긴다.

### Field Metric

기존 공간 통계 이름을 그대로 쓴다.

```text
total_time
visit_rate
conditional_dwell
time_utilization
walk_utilization
```

Memory Place의 `exposure_count`는 특정 footprint를 충분히 칠한 산책 수이고 지도 전체 metric과
다른 개념이다.

## 분모

비율은 질문에 맞는 분모를 이름과 함께 반환한다.

```text
selected_capsules       Walk Selector가 고른 전체
contributing_capsules   해당 field metric을 계산할 재료가 있는 산책
exposed_count           특정 Memory Place를 만난 산책
judgeable_count         capability와 품질이 해당 질문을 허용한 노출
unjudgeable_count       노출됐지만 판단할 수 없는 산책
```

`탐색 증언 / 전체 선택 산책`과 `탐색 증언 / 판단 가능한 장소 노출`은 다른 질문이다. API나
문장이 분모 이름을 숨기지 않는다.

## View Receipt

결과에는 최소 다음 재현 정보를 붙인다.

```text
selector_fingerprint
view_as_of
total / selected / contributing capsules
context known / unknown
pin count
paint_fp
field_metric / normalization
context / quality / claim policy version
```

다른 `paint_fp` 세대는 같은 field에 섞지 않는다. 세대가 공존할 때 어떤 세대를 보여줄지는 후속
제품 정책이고, 조용히 합치는 것은 허용하지 않는다.

첫 실행 구현은 [결정 #76](../decisions/2026-09-01-spatial-diary-view-v0.md)에 따라 기간(KST
달력)·강수(`rain|dry|unknown`)·낮밤(`day|night|unknown`)을 AND로 컴파일하고,
`visit_rate|walk_utilization`만 계산한다. Pin이 아직 없으므로 Entry Selector는 비어 있어야 하며
receipt의 `pin_count`는 0이다. 선택된 paint 세대가 둘 이상이면 조용히 일부를 버리지 않고
실패한다.

공개 query는 인증 principal이 소유한 `dog_id`만 읽고, 색인과 cell을 하나의 repeatable-read
snapshot에서 조립한다. v0 동기 응답의 운영 상한(366일·2,000 후보 index·400 선택 Capsule·
100,000 원시 cell·50,000 결과 cell)을 넘으면 부분 결과를 반환하지 않고 413으로 실패한다.
context known 수는 필터에 사용한 축이 모두 알려진 Capsule 수이며, 무필터일 때는 지원하는 모든
context 축을 요구한다.

[결정 #77](../decisions/2026-09-01-spatial-diary-episode-pin-v0.md)부터 선택된 Capsule의 안정 Pin을
같은 repeatable-read snapshot에서 불러온다. `EntrySelector.subject_roles`와 `meaning_codes`는
Attestation claims에 적용되고 두 축은 AND다. 이 필터는 `pins`와 `receipt.pin_count`만 바꾸며
Walk cohort·Cellophane Field·selected/contributing 분모는 바꾸지 않는다. Pin 응답은 footprint와
claims를 포함하고, 실제 제시 문장은 Pin의 `source_offer_id`로 immutable Offer에서 읽는다.

## 표현

통계는 원 Cellophane과 Micro Observation을 읽는다. 보수적 연속 복원 Field는 사용자 표시
전용이다. 복원 결과를 후보 생성, 통계, Memory Place 형성에 다시 넣지 않는다.

```text
Episode Pin       안정적인 한 장면
marker cluster    현재 줌에서 겹침을 줄이는 임시 표현
Memory Place      여러 산책을 관통하는 도메인 identity
```

세 객체를 같은 것으로 취급하지 않는다. 축소 화면에서 cluster와 Memory Place가 모두 숫자를
보이더라도 시각 문법을 구분한다.

## 시간 투영

같은 Pin 집합은 세 방식으로 읽힌다.

```text
공간 투영  Cellophane Field + Pins + Memory Places
시간 투영  한 session의 Pins를 event_at 순으로 정렬한 WalkJournalProjection
장소 투영  한 Memory Place의 Pins를 날짜순으로 정렬한 Biography
```

자동 나레이션은 현재 증거와 claim policy로 재생성한다. 사용자가 확정한 문장만 별도 snapshot
결정의 대상이다.

## 비교

필터 여러 개는 하나의 ViewSpec으로 컴파일한다. 비교는 독립된 ViewSpec A/B를 사용한다.
v1은 범용 비교 DSL을 정의하지 않는다. 첫 비교 후보는 같은 Memory Place에서 `rain`과 `dry`의
노출·judgeable·attested count를 나란히 보는 것이다. 결과는 조건별 관측 차이지 인과가 아니다.
