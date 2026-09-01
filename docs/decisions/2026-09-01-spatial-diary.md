---
status: adopted
decision: 74
adopted_at: 2026-09-01
---
# 산책 증거는 Capsule로 봉인하고, 사용자가 남긴 Pin을 조건에 따라 공간 일기로 다시 읽는다

이 결정은 [memory-engine](../explorations/walk/memory-engine.md)과
[behavior-anchor](../explorations/walk/behavior-anchor.md)의 전체를 채택하지 않는다. 두 탐색에서
제품 한 바퀴를 닫는 데 필요한 좁은 경계만 꺼낸다.

결정 #57은 산책 데이터의 좌표 민감도와 삭제 경계를, #58은 산책을 묶는 `dog_id`를, #69는
원좌표 purge 뒤 남는 산책별 Cellophane을 정했다. 이어진
[센서 내성 평가](../research/2026-09-01-sensor-robustness.md)는 보수적 복원기가 입력을 더 새게
하지는 않지만 완만한 GPS drift를 고치지도 못하며, accuracy 거부는 공간 모양보다 관측 시간을
줄일 수 있음을 확인했다.

따라서 다음 제품 단계는 Territory 표현을 더 다듬는 것이 아니라 **어떤 증거로 무엇을 말해도
되는지 보존한 뒤, 사용자가 의미를 붙인 장면을 지도에서 다시 읽는 것**이다.

## 제품 정의

> **Walk Capsule Core는 산책 증거를 봉인하는 쓰기 모델이고, Spatial Diary View는 여러
> Capsule과 Episode Pin을 조건에 따라 다시 펼치는 읽기 모델이다.**

관계는 다음과 같다.

```text
Territory / Cellophane  선택된 산책들의 공간적 배경
Episode Pin             한 산책에서 사용자가 기억으로 남긴 공간적 문단
Memory Place            여러 산책의 Pin이 반복되어 생긴 안정적인 장소 identity
Spatial Diary View      같은 증거를 조건과 통계 질문에 따라 다시 조립한 현재의 일기장
```

한 산책의 Pin을 `event_at` 순으로 읽으면 `WalkJournalProjection`, 한 장소에 연결된 Pin을 날짜순으로
읽으면 `MemoryPlaceBiography`다. 둘은 새 원본이 아니라 같은 Capsule·Pin·증언의 시간 투영이다.

## 결정 1 — Capsule은 거대한 JSON이 아니라 봉인 manifest다

`WalkCapsuleManifest`는 기존 산책 결과를 복사하지 않는다. 다음 자식이 `session_id` 아래 완전히
생성됐고 어느 버전·capability로 봉인됐는지를 선언한다.

```text
WalkCapsuleManifest [FROZEN]
├─ WalkFacts / 기존 canonical 파생
├─ Macro Cellophane
├─ Micro Observation
├─ MeasurementReceipt
├─ TrailContextSnapshot
├─ dog_id / provenance
└─ ObservationCapability[]
```

Capsule에는 Place, 행동 원인, 중요도, 일기 문장, `rainy` 같은 현재 분류를 얼리지 않는다.

- 사실·당시 확보한 문맥은 동결한다.
- `unknown`도 동결한다. 나중의 외부 데이터로 과거를 자동 보충하지 않는다.
- 판단·Place·나레이션은 현재 정책으로 재계산한다.
- 사용자가 확정한 의미만 append-only 역사로 보존한다.

manifest는 `walk_session`의 1:1 자식이며 별도 capsule identity를 만들지 않는다. 삭제와 subject
귀속은 #57·#58의 세션 경계를 그대로 따른다.

## 결정 2 — MeasurementReceipt는 원시 측정량이고 ClaimAllowance는 파생 정책이다

`신뢰도 82점` 같은 하나의 점수는 저장하지 않는다. drift는 fix 보존과 인정 시간이 정상이어도
절대 위치를 움직였고, 낮은 accuracy 거부는 위치 누출보다 시간 손실을 만들었다. 서로 다른 실패를
한 숫자로 접으면 어떤 주장을 제한해야 하는지 복구할 수 없다.

동결하는 것은 이름 붙은 원시 분자·분모다.

```text
received / accepted fix count
거부 종류별 count
jump / gap / explicit break count
session wall time
canonical segment time
gap elapsed time
reported / accepted accuracy count와 p50·p90
drift assessment와 method
```

`accepted_time_ratio`처럼 분모가 숨은 비율은 영수증에 넣지 않는다. 명시적 pause와 관측 공백을
어떤 분모에 포함할지는 질문마다 다르다. 비율은 소비자가 원시값과 정책 버전으로 계산한다.

```text
MeasurementReceipt [FROZEN]
→ ClaimAllowance [DERIVED, policy_version]
   temporal / spatial / interpretation
```

현재 휴대폰 fix만으로 완만한 drift의 부재를 증명할 수 없으므로 초기 상태는 `not_assessed`다.
`false`나 `safe`로 저장하지 않는다. `suspected`를 내리려면 평가 method를 함께 남긴다.

## 결정 3 — Candidate, Offer, Interaction, Attestation, Pin은 서로 다른 객체다

```text
EpisodeCandidate [DERIVED]
        ↓ 실제 사용자에게 제시
EpisodeOfferSnapshot [FROZEN]
        ├─ OfferInteraction [APPEND-ONLY]
        └─ WalkAttestation [APPEND-ONLY, 실제 응답이 있을 때만]
                  ↓ memory_action=save
             EpisodePin [STABLE IDENTITY]
```

### Candidate

현재 micro observation과 후보 정책으로 다시 계산할 수 있다. 후보 정책이 바뀌면 사라지거나
합쳐질 수 있다. 아직 사용자 역사가 아니다.

### Offer snapshot

Candidate가 실제로 사용자에게 제시된 순간에만 생긴다. 사용자가 본 관측 범위, 근거값, prompt,
candidate·claim policy 버전을 동결한다. 사용자가 후보를 거부하거나 확신하지 못해도 무엇에 대한
응답이었는지 남는다.

### Offer interaction

`viewed | dismissed | expired`는 제안의 노출 생명주기다. **무응답은 증언이 아니다.** `skipped`
attestation을 만들지 않는다. `잘 모르겠음`은 사용자가 검토하고 답한 `uncertain` 증언이므로
무응답과 다르다.

### Attestation

사용자 응답은 다음 축을 분리한다.

```text
review_disposition  confirmed | rejected | uncertain
claims[]            subject_role + meaning_code + vocabulary_version
memory_action       save | dismiss
elicitation_mode    system_offer | in_walk_bookmark | post_walk_manual | photo_associated
```

사건을 확인하는 것과 지도에 기억으로 남기는 것은 다른 행위다. `confirmed + dismiss`와
`uncertain + save` 모두 가능하다. 정정은 기존 행 update가 아니라 `supersedes_attestation_id`를
가진 새 행이다.

### Pin

Pin은 사용자가 공간 일기에 남기기로 한 안정적인 기억 identity다. 시스템 Offer는 Pin 생성의
유일한 경로가 아니다.

```text
system_offer
in_walk_bookmark
post_walk_manual
photo_associated
```

`representative_point`는 지도에 아이콘을 놓는 라벨 앵커일 뿐 정확한 사건 좌표 주장이 아니다.
공간 주장은 `event_footprint`가 담당한다. 사후 수동 입력처럼 시각을 복원할 수 없으면
`event_at = null`, `temporal_precision = unknown`으로 남긴다.

## 결정 4 — 동적 문맥 원자와 현재 필터 facet을 분리한다

Capsule에 얼리는 것은 외부 원천이 준 당시 값과 provenance다.

```text
TrailContextSnapshot [FROZEN]
walked_at
source_observed_at
captured_at
provider
precipitation / temperature / humidity / sun elevation
status = captured | partial | unknown | failed
```

`rain`, `autumn`, `evening`은 현재 정책의 분류다.

```text
TrailContextSnapshot
→ ContextFacet [DERIVED, policy_version]
```

`unknown`은 `dry`나 `day`로 들어가지 않는다. Event Context는 Pin의 불변 열이 아니라 append-only
snapshot 자식이다. 동적 환경은 Trail Context에서 사건 시각과 가까운 값을 읽고, 토지피복·수변·
도로·시설 같은 공간 문맥은 Pin 승격 뒤 별도 snapshot으로 확보할 수 있다.

## 결정 5 — Walk Selector는 분모, Entry Selector는 overlay다

```text
Walk Selector
→ 어떤 Capsule을 공간 배경과 노출 분모에 넣는가

Entry Selector
→ 선택된 Capsule 안에서 어떤 Pin을 보여주는가
```

`비 오는 가을 저녁 + 탐색`을 조회할 때 배경은 비 오는 가을 저녁 산책 전체다. 탐색 Pin이 있었던
산책만 배경에 남기면 사건이 없었던 노출이 사라져 `4/9`를 `4/4`로 왜곡한다.

Quality Policy도 Walk Selector에서 분리한다. 낮은 품질 산책을 cohort에서 조용히 지우면 날씨나
기기 상태와 품질이 함께 변할 때 비교 자체가 편향된다. 산책은 선택 집합에 남기고 질문별로
`contributing`, `judgeable`, `unjudgeable`을 나눈다.

필터 여러 개는 화면 field 여러 장을 물리적으로 포개는 뜻이 아니다. 하나의 `ViewSpec`으로 AND
컴파일해 읽을 수 있는 배경 하나와 Pin overlay 하나를 만든다. 비교는 독립된 ViewSpec A/B다.

## 결정 6 — 자동 일기와 장소 전기는 읽기 결과다

```text
WalkJournalProjection
= Capsule facts + Trail Context + Episode Pins + 현재 narration policy

MemoryPlaceBiography
= 안정적인 Memory Place identity + 현재 selector에 맞는 Pin timeline과 분모
```

자동 요약 때문에 `WalkJournal` 원본을 하나 더 만들지 않는다. 사용자가 제목·요약·대표 사진을
수정하거나 특정 버전으로 저장·공유하는 기능이 생길 때만 `PublishedJournalSnapshot`을 별도
결정으로 연다.

Memory Place identity는 필터에 따라 생기고 사라지지 않는다. 사용자가 이름 붙이기 전 후보
geometry는 재계산할 수 있고, 이름 붙인 뒤 identity는 고정하되 footprint는 새 관측으로 개선할
수 있다. Place 생성 알고리즘 자체는 이 결정에서 고르지 않는다.

## 결정 7 — 보수적 연속 Field와 화면 marker cluster는 표현이다

```text
통계·노출·Place 계산  원 Cellophane + Micro Observation
사용자 지도 표시      Conservative Reconstructed Field
```

복원 Field를 후보 생성·통계·Memory Place 형성에 다시 넣지 않는다. 표현 결과가 새 측정값으로
역수입되기 때문이다.

화면 marker cluster도 Memory Place가 아니다. cluster는 현재 줌에서 아이콘 겹침을 줄이는 표현이고,
Memory Place는 서로 다른 산책의 사건과 노출 분모를 가진 도메인 identity다.

## capability와 부재의 계약

> [결정 #81](2026-09-01-negative-spatial-claim-eligibility.md)은 아래 부재 조건에
> `drift_assessment=not_suspected`와 평가 방법이라는 적극적 자격을 추가한다.

과거 Capsule에 어떤 observation generation이 없으면 그 행동이 없었다고 말할 수 없다.

```text
exposure    exposed | not_exposed | uncertain
capability  supported | unsupported
observation observed | not_observed | unjudgeable
```

`exposed + supported + negative spatial claim eligible + not_observed`일 때만 해당 capability 범위
안의 부재를 말할 수 있다.
`unsupported`와 `unjudgeable`은 음성 예제가 아니다.

## 삭제와 개인정보

Cellophane과 Pin은 모두 좌표를 포함한다. Pin은 사건 시각·사용자 메모·사진·반복 장소 연결까지
가질 수 있어 한 장의 Cellophane보다 더 민감할 수 있다.

세션 삭제는 다음 기여를 모두 제거한다.

```text
Capsule → Macro → Micro → Receipt → Context
        → Offer → Interaction → Attestation → Pin → Event Context
        → Memory Place contribution 재계산
```

숨김으로 삭제를 흉내내지 않고 #57의 cascade 원칙을 따른다. 구체 보관 일수, 공유 projection,
집 주변 마스킹은 이 결정에서 숫자나 알고리즘으로 정하지 않는다. 다만 private diary의 실제 Pin과
시각을 그대로 외부 공유하는 경로는 열지 않는다.

## 이 결정이 정하지 않는 것

- DB 테이블 이름·마이그레이션·HTTP 경로
- 행동 어휘와 아이콘 종류
- Candidate 점수·문턱·한 산책당 개수
- Event Context 제공자와 payload 스키마
- Memory Place 형성·병합·분할 알고리즘
- 실제 보관 일수와 공유 UX
- LLM 나레이션과 Published Journal
- 범용 비교 DSL

위 항목을 열어 둬도 객체의 진실성과 생명주기는 바뀌지 않는다. 순수 계약은
[`app/features/spatial_diary/contract.py`](../../app/features/spatial_diary/contract.py), 저장 전
경계는 [`walk-capsule`](../contracts/walk-capsule.md), 읽기 경계는
[`spatial-diary-view`](../contracts/spatial-diary-view.md)가 고정한다.

## 이 결정이 바뀌어야 하는 신호

- 한 산책의 자동 projection만으로 사용자 정정·공유 이력을 복구할 수 없어 영구 Journal 원본이 필요하다
- 사용자에게 제시하지 않은 Candidate까지 Offer 역사로 보존해야 할 실제 제품 요구가 생긴다
- Pin이 아닌 시간순 저해상도 궤적 없이는 필요한 일기 장면을 만들 수 없다는 측정이 나온다
- quality가 cohort 선택과 독립일 수 없는 질문이 생기고, 그 편향을 분리해 설명할 수 없다
- 보수적 표시 Field를 통계에 사용해야만 복구되는 정보가 있다는 실험 결과가 나온다
