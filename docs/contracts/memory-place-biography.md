# Memory Place biography v0

Memory Place는 지도 필터가 만든 marker cluster가 아니다. 서로 다른 산책에서 저장된 Episode Pin
두 개 이상을 사용자가 같은 장소로 승격할 때 생기는 안정 identity다. 생성 뒤 필터가 바뀌거나
원천 산책 하나가 삭제돼도 `place_id`와 생성 당시 footprint는 남는다. Pin membership은 원천
Pin 삭제를 따라 제거되고 biography는 남은 Capsule과 membership으로 다시 계산한다.

## 쓰기 계약

```text
PUT /spatial-diary/memory-places/{place_id}
  dog_id
  seed_pin_ids[2..100]      서로 다른 session이 최소 2개
  label?                    사용자가 붙인 장소 이름

PUT /spatial-diary/memory-places/{place_id}/memberships/{pin_id}

GET /spatial-diary/dogs/{dog_id}/memory-places
  안정 장소 marker 목록
```

v0는 자동 거리 clustering 임계값을 정하지 않는다. seed Pin은 명시적으로 선택하며, 새 Pin은
기존 장소 footprint와 겹칠 때만 한 장소에 추가 연결할 수 있다. Pin 하나는 동시에 두 Memory
Place에 속하지 않는다. 최초 footprint는 seed Pin circle을 모두 덮는 circle snapshot이고 최대
반경은 5km다. footprint 개선과 revision history는 후속 범위다.

## biography의 산책별 판정

```text
macro_exposure = exposed | uncertain | not_exposed
capability     = supported | unsupported
observation    = observed | not_observed | unjudgeable
```

Cellophane 셀 중심이 장소 circle 안에 있으면 `exposed`, 셀 중심은 밖이지만 육각 반경이 circle과
겹치면 `uncertain`, 어느 것도 아니면 `not_exposed`다. v0의 peak 문턱은 0이며 정책 버전으로
영수증에 남긴다.

`not_observed`는 다음을 모두 만족할 때만 말할 수 있다.

- macro exposure가 `exposed`
- Capsule이 현재 `low_motion` generation을 보존
- MeasurementReceipt가 평가 방법과 함께 `drift_assessment=not_suspected`를 보존
- 장소 footprint와 겹치는 slow observation이 없음

나머지는 `unjudgeable`이며 이유를 함께 반환한다. 따라서 장소를 지나지 않은 산책, 셀 경계만
스친 산책, 과거 generation이라 관측 능력이 없는 산책, drift를 평가하지 않았거나 근거가
부족하거나 의심되는 산책을 “행동하지 않았다”의 분모에 넣지 않는다. 각 reading은
`negative_spatial_claim`의 독립 정책 버전·최종 자격·macro exposure·capability·drift 상태와
모든 `blocking_reasons`를 반환한다. 따라서 `eligible=true`는 drift gate만 아니라 부정 주장에
필요한 세 gate가 모두 통과했다는 뜻이다. 차단된 주장은 실제 상태와 일치하는
`spatial_drift_*` 이유를 남긴다. 응답은
selected/exposure/capability/judgeable/observed/not-observed를 모두 원시 count로 보존하고 비율
하나로 합치지 않는다.

양성 관측은 비대칭이다. 실제 slow observation이 있으면 `not_assessed` 또는
`insufficient_evidence`에서도 approximate `observed`로 남길 수 있다. `suspected`는 양성·부정
공간 관측 모두를 `unjudgeable`로 만든다. 상세 근거는 [결정 #81](../decisions/2026-09-01-negative-spatial-claim-eligibility.md)에 있다.

Timeline은 선택된 Walk cohort 안의 membership Pin과 그 Pin을 만든 Attestation을 시간순으로
돌려준다. 그래서 marker를 누르면 원래 review disposition과 사용자 claim을 다시 읽을 수 있다.
Entry Selector는 timeline과 claim count만 거르며 산책 cohort나 노출·관측 분모를 바꾸지 않는다.

## 첫 비교

```text
POST /spatial-diary/memory-places/{place_id}/comparisons/precipitation/query
```

base selector의 기간·낮밤 조건을 공유한 채 `rain`과 `dry` biography를 나란히 계산한다.
강수 `unknown` 산책은 어느 쪽에도 뒤집어 넣지 않고 `excluded_unknown_context_walks`로 센다.
응답의 `comparison_kind`는 `observational`로 고정하며 차이를 원인이나 효과로 서술하지 않는다.
