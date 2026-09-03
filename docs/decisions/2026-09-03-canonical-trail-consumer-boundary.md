---
status: adopted
decision: 84
adopted_at: 2026-09-03
---
# CanonicalTrail은 한 번 계산하는 transient 증거이고, 소비자는 각자의 자격과 수명을 가진다

현재 산책 finalize는 원순서 fix를 한 번 검증해 `Segment[]`와 `GapSpan[]`를 만든 뒤
`WalkFacts`, motion event, Cellophane, Micro Observation, MeasurementReceipt를 생성한다.
이 중 `Segment[]`는 이미 시설 occurrence와 territory 계산도 함께 소비한다. 그러나 이 공통
입력이 이름 없는 구현 중간값으로만 남아 있으면 새 일기 동선과 점령 게임이 다음 두 극단 중
하나로 흐르기 쉽다.

- 소비자마다 raw fix를 다시 걸러 서로 다른 산책을 사실로 만든다.
- 공통 입력뿐 아니라 저장 객체·실패·UI까지 하나의 범용 Trail 도메인으로 합친다.

둘 다 피한다. 재사용은 **검증된 센서 사실을 한 번 만드는 지점까지만** 적용한다. 그 뒤의
개인 일기와 점령 게임은 같은 증거 생산자를 쓰지만 서로 다른 제품 도메인이다.

## 결정 1 — `CanonicalTrail`은 저장 엔티티가 아니라 finalize 중의 좁은 읽기 경계다

```text
raw walk_fix[]
  ↓ 시간·accuracy·chain·gap·jump 정책을 한 번 적용
CanonicalTrail [TRANSIENT]
  ├─ session_id / dog_id / calculation_version
  ├─ ordered Segment[]
  ├─ GapSpan[] / explicit chain boundary
  └─ canonical quality evidence
```

`CanonicalTrail`은 원래 `compute_facts()`가 만들던 `ComputedFacts.segments`·`gaps`와 품질 결과에
이미 존재하던 개념의 이름이다. 구현은 이를 `CanonicalWalkComputation.trail`로 드러내되 HTTP·
DB 계약은 바꾸지 않고 기존 결과가 같음을 회귀 테스트로 잠근다.

`Segment` 끝점과 `GapSpan`에는 좌표와 시각이 있으므로 CanonicalTrail은 raw와 같은 민감 구간에
있다. DB·캐시·이벤트 버스·로그에 영구 보관하지 않고 finalize 트랜잭션 밖으로 수명을 늘리지
않는다. 원좌표가 purge되면 함께 사라진다.

`accepted_fixes`는 더 좁다. MeasurementReceipt의 분포를 만드는 데 필요한 전용 transient
입력이지 모든 소비자가 받을 공용 필드가 아니다. 새 소비자는 Segment와 gap으로 답할 수 없는
이유를 증명하지 못하면 accepted fix 열을 직접 받지 않는다.

현재 Trail Context는 산책 중간 시각에 가장 가까운 accepted fix의 위치를 사용한다. 이 동작을
보존하기 위해 producer가 `midpoint_sample` 한 점만 CanonicalTrail에 복사한다. Context 소비자에
전체 accepted fix 열을 넘기거나, 한 점짜리 산책의 문맥 위치를 잃지는 않는다.

## 결정 2 — 공통 canonical validity와 소비자별 eligibility를 분리한다

Canonical 계산은 무엇을 수용했고 어디에서 관측이 끊겼는지를 한 번만 정한다. 그러나 그 결과가
존재한다고 모든 제품 주장이 허용되지는 않는다.

```text
CanonicalTrail
  + ConsumerPolicy(policy_version)
  → ConsumerEligibility(status, reason_codes, policy_fp)
  → consumer projection 또는 명시적 unavailable
```

소비자는 자기 질문에 맞는 자격을 별도로 판정한다.

| 소비자 | CanonicalTrail에서 읽는 것 | 별도로 결정할 것 |
|---|---|---|
| `WalkFacts` | 시간·거리·이동 구간 | 계산 버전의 집계 규칙 |
| Cellophane | 연속 Segment와 chain | paint generation·붓·표현 자격 |
| Micro Observation | Segment와 GapSpan | observation generation·claim allowance |
| `WalkDiaryRoute` 후보 | 순서·chain·gap | 단순화·마스킹·보관·표시 자격 |
| `TerritorySiteEncounter` 후보 | 순서 있는 Segment | 게임 참여·접촉·품질·사이트 정책 |

`ineligible`은 사건이 없었다는 뜻이 아니다. 출력이 없으면 `unavailable`과 이유·정책 버전을
남길 수 있어야 하며, 소비자는 그것을 0건 관측이나 빈 동선으로 바꾸지 않는다. 낮은 품질을
보상하려고 점령 반경이나 일기 경로를 조용히 넓히지도 않는다.

정확한 status enum, reason code, 문턱값은 각 소비자 결정에서 정한다. 이 결정이 고정하는 것은
**공통 수용 여부를 다시 계산하지 않고, 제품별 발언 자격을 별도로 설명한다**는 규율이다.

## 결정 3 — 소비자는 형제 결과가 아니라 CanonicalTrail을 직접 읽는다

```text
                         ┌─ WalkFacts / current Capsule children
raw fix → CanonicalTrail ├─ WalkDiaryRoute candidate
                         └─ TerritorySiteEncounter candidate
```

금지하는 연결은 다음과 같다.

- Cellophane을 궤적으로 역복원해 일기 순서나 점령 접촉을 판정하지 않는다.
- 개인정보를 줄인 `WalkDiaryRoute`로 권위 있는 점령 접촉을 판정하지 않는다.
- 점령 Encounter·Capture·상태를 자동으로 Episode Pin이나 일기 문장으로 승격하지 않는다.
- Cellophane의 진하기를 점령력·소유권·보상으로 읽지 않는다.
- 일기·게임의 projection을 다시 산책 측정 사실로 역수입하지 않는다.

따라서 일기와 게임이 공유하는 것은 **같은 evidence producer**이지 저장 모델, 상태 머신,
보관 정책, 실패 정책, 화면 상태가 아니다. 공통 plugin framework나 범용 projection bus도 만들지
않는다. typed immutable 입력과 명시적인 순수 projector면 충분하다.

## 결정 4 — walk는 생산하고 application layer가 조립한다

`features.walk`가 canonical 계산과 현재 필수 Capsule 자식을 소유한다. 향후
`features.spatial_diary`와 `features.territory.game`은 선언된 walk 계약만 소비하고 walk로
역방향 의존을 만들지 않는다. 여러 projector와 저장을 호출하는 finish orchestration은
application layer의 책임이다.

```text
application finish orchestrator
  ├─ features.walk canonical producer
  ├─ adopted mandatory projectors
  └─ enabled optional product consumers
```

현재 #75가 채택한 필수 자식은 그대로 한 트랜잭션에서 manifest보다 먼저 저장하고, 하나라도
실패하면 raw fix를 보존한 채 rollback한다. 이 결정만으로 `WalkDiaryRoute`나
`TerritorySiteEncounter`를 필수 자식에 추가하지 않는다.

후속 소비자는 다음 실패 규율을 지켜야 한다.

- 아직 채택되지 않았거나 활성화되지 않은 소비자 때문에 정상 산책 finish를 막지 않는다.
- 사용자가 명시적으로 만든 Capture 같은 증거가 있다면 소비자 실패를 조용히 무시하고 raw를
  지우지 않는다.
- 그렇다고 외부 판정 완료를 기다리며 raw 전체를 무기한 보관하지 않는다. purge 전에 필요한
  최소 evidence envelope를 봉인할지, 별도 `purge_pending` 수명을 둘지는 촬영·판정 결정에서
  고른다.

## 결정 5 — 점령 claimant v0는 정확히 하나의 `claiming_pet_id`다

가구·팀·보호자 중 누가 장기 점령 주체인지 아직 결정하지 않는다. 현재 산책 계약도 세션마다
불투명 `dog_id` 하나를 받는다. 따라서 첫 점령 계약은 다음의 좁은 가계약으로 시작한다.

```text
PetClaimant v0
  claiming_pet_id: string

TerritorySiteAttestation
  session_id
  site_id
  capture_id
  claiming_pet_id

TerritorySiteClaimState
  site_id
  claiming_pet_id
  projected_state
  policy_version
```

- 한 Attestation과 현재 ClaimState에는 정확히 한 `claiming_pet_id`만 있다.
- v0에서는 `claiming_pet_id == walk_session.dog_id`여야 한다.
- 향후 세션이 여러 참여견을 지원하면 선택된 ID가 그 세션의 참여견 집합에 있어야 한다.
- 한 세션·Encounter·Capture가 강아지 수만큼 복제되거나 점령력 배수를 만들지 않는다.
- 로그인한 보호자 계정은 요청 권한과 감사의 actor다. 그것을 곧 영토 claimant의 장기 제품
  identity로 확정하지 않는다.
- 상태 객체 이름에 `Dog`를 박지 않는다. 가구 또는 팀 claimant로 바뀔 때 게임 원장 전체를
  이름부터 갈아엎지 않기 위해서다.

wire와 DB에는 지금 필요하지 않은 `claimant_type`이나 Household 테이블을 미리 만들지 않는다.
향후 실제 공동 소유 요구가 확인되면 새 결정과 명시적 migration으로 `PetClaimant`를
`HouseholdClaimant` 등에 옮긴다. `claiming_pet_id`의 뜻을 몰래 바꾸지는 않는다.

## #69·#74·#75와의 관계

- #69의 **단순화 궤적 영구 저장 금지**는 유지된다. `WalkDiaryRoute`는 아직 후보이며,
  마스킹·단순화·보관 수명이 측정되어 별도 결정이 #69의 범위를 명시적으로 바꾸기 전에는
  저장하지 않는다.
- #74의 Capsule과 Spatial Diary 권위 분리는 유지된다. Trail이 Pin이나 사용자 의미를 만들지
  않는다.
- #75의 current mandatory seal과 purge 원자성은 유지된다. 새 필수 projector는 별도 결정 없이
  manifest 앞에 끼워 넣지 않는다.

## 이 결정이 정하지 않는 것

- `CanonicalTrail`의 Python 타입명과 contract module 경로
- `WalkDiaryRoute`의 채택 여부, 단순화·마스킹 수치, 보관 일수
- Territory Site 접촉 반경과 모든 산책/opt-in 산책 중 어느 범위에서 Encounter를 만들지
- Capture media 보관, VLM, outbox, 재시도와 purge barrier의 구체 상태 머신
- 점령·강화·시즌·연결망 projection 규칙
- `PetClaimant` 이후의 가구·팀 identity와 migration
- Android 지도 renderer와 화면 상태

## 이 결정이 바뀌어야 하는 신호

- 서로 다른 소비자가 실제로 다른 canonical acceptance를 가져야만 답할 수 있는 측정 결과가 나온다
- CanonicalTrail을 finalize 밖에 보관하지 않고는 채택된 필수 projection을 안정적으로 만들 수 없다
- 단일 `claiming_pet_id` 때문에 다견·공동 보호자 사용에서 점령 기회나 표시가 실제로 왜곡된다
- 사용자 Capture를 보존하면서 정상 finish와 raw purge를 함께 만족할 bounded envelope를 만들 수 없다
