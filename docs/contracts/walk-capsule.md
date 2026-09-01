# Walk Capsule과 공간 일기 기억 경계 v1

결정 #74가 채택한 내부 소비자 계약이다. `walk-record.md`의 outbound 사실 계약을 늘리지 않고,
그 사실과 결정 #69의 Cellophane을 원좌표 purge 전에 어떻게 봉인하고 사용자 기억과 어떻게
연결하는지를 정의한다. 현재 DB 스키마나 HTTP API가 아니다.

순수 실행 계약은 `app/features/spatial_diary/contract.py`가 고정한다. 구현이 테이블을 이 모델과
1:1로 만들 필요는 없지만 아래 객체를 한 상태나 한 행으로 합쳐 의미를 잃으면 안 된다.

## 객체 수명

| 객체 | 생성 시점 | 성질 | 삭제 단위 |
|---|---|---|---|
| `WalkCapsuleManifest` | 산책 파생 결과가 모두 준비된 뒤 | frozen, 세션 1:1 | session/subject |
| `MeasurementReceipt` | raw fix purge 전 | frozen raw evidence | session/subject |
| `TrailContextSnapshot` | capsule seal 전 best-effort | frozen, unknown 포함 | session/subject |
| `EpisodeCandidate` | 조회 시 | derived | 저장 안 함 |
| `EpisodeOfferSnapshot` | 후보를 실제 제시할 때 | frozen | session/subject |
| `OfferInteraction` | view/dismiss/expire | append-only, 증언 아님 | session/subject |
| `WalkAttestation` | 사용자가 실제 답할 때 | append-only, supersedes | session/subject |
| `EpisodePin` | 사용자가 기억으로 남길 때 | stable identity | session/subject |
| `PublishedJournalSnapshot` | 사용자가 자동 일기를 확정할 때 | frozen, private | session/subject |
| `ClaimAllowance` | 영수증을 현재 정책으로 읽을 때 | derived | 저장 안 함 |

Pin을 만든 최초 Attestation은 Offer 응답 역사로 남는다. 이후 의미 정정은
[`Pin Attestation correction`](pin-attestation-correction.md)에 따라 같은 Pin에 append되고,
현재 Journal·Memory Place는 correction chain의 head를 읽는다.

## Capsule 봉인

manifest는 기존 결과를 복제한 JSON bundle이 아니다. `session_id` 아래 다음 필수 자식이 완전히
생성됐음을 선언하는 영수증이다.

```text
Walk facts/canonical children
Macro Cellophane
Micro observations
Measurement receipt
Trail context captured/partial/unknown/failed
Observation capabilities
```

필수 자식 저장과 manifest 생성, raw fix purge는 후속 저장 구현에서 하나의 멱등 트랜잭션이 된다.
manifest가 있으면 같은 finish 요청은 파생을 다시 계산하지 않고 봉인된 결과를 반환해야 한다.

첫 저장 구현은 [결정 #75](../decisions/2026-09-01-walk-capsule-finalize.md)에 따라
`paint-v2 · hex-v1 · 8u · NARROW_STEP · 1.5m sample step`을 사용한다. 셀 payload는
`walk_cellophane_cell` 행으로 분리하고, receipt·context·manifest와 함께 session cascade를 탄다.
manifest가 마지막에 성공한 뒤에만 raw fix를 purge한다.

## 시간 영수증

v1은 다음 시간을 분리한다.

```text
session_wall_time_s       세션 시작과 종료 사이 벽시계 시간
canonical_segment_time_s 실제로 수용된 Segment의 dt 합
gap_elapsed_s             GapSpan의 dt 합 — 관측이 아니라 관측 부재
```

`accepted_time_ratio`는 저장하지 않는다. 명시적 pause, jump 주변, accuracy 거부 주변을 어느 분모에
넣는지는 질문별 정책이다. 소비자가 비율을 만들면 사용한 분자·분모 이름과 policy version을 결과
영수증에 남긴다.

accuracy 분포도 둘이다.

```text
reported accuracy  session 안에서 accuracy를 보고한 raw fix
accepted accuracy  canonical 필터를 통과했고 accuracy를 보고한 fix
```

거부된 값이 빠진 accepted 분포만 저장하면 센서가 나빴던 사실이 사라지므로 둘을 같이 보존한다.

## Context

`TrailContextSnapshot`은 원천값을 저장하고 `rainy`, `evening`, `autumn`을 저장하지 않는다.

```text
walked_at            산책 시각
source_observed_at   원천 관측이 설명하는 시각
captured_at          시스템이 값을 확보한 시각
provider
status
raw context atoms
```

`unknown`은 성공적인 빈 값이다. `failed`는 시도 실패라 failure reason을 가진다. 둘 다 dry나
clear로 해석하지 않는다. Event Context는 Capsule 필수 자식이 아니며 Pin 승격 뒤 append-only
snapshot으로 붙는다.

현재 기본 provider는 `unknown`을 반환한다. 실제 provider 예외와 다른 session의 응답은
`failed + provider_error:<ExceptionType>`으로 정규화하며 외부 예외 원문은 저장하지 않는다.
문맥 실패는 Capsule seal과 purge를 막지 않는다.

## Capability

capability는 현재 generation이 무엇을 판정할 수 있다는 주장이 아니라 **어떤 현상을 다시 읽을
재료를 보존했는지** 선언한다.

```text
ObservationCapability(name="low_motion", generation=1)
ObservationCapability(name="gap", generation=1)
```

미래 generation의 capability가 없는 Capsule에서 그 현상이 관측되지 않았다는 이유로 음성 판정을
만들지 않는다.

## Offer와 증언

Candidate는 다시 계산 가능하지만 실제로 사용자에게 보여준 Offer는 역사다. Offer snapshot은
source observation identity, event footprint, evidence vector, prompt text와 정책 버전을 가진다.

Interaction은 제안의 노출 상태만 기록한다.

```text
viewed     user
dismissed  user
expired    system
```

무응답에는 Attestation이 없다. 사용자가 `잘 모르겠음`을 누른 경우에만 `uncertain` Attestation이
생긴다.

Attestation은 다음 두 질문을 합치지 않는다.

```text
이 후보는 무엇이었나?       review_disposition + claims
지도에 기억으로 남길 것인가? memory_action
```

`claims`는 `subject_role`과 versioned `meaning_code`를 가진다. 의미 어휘는 후속 결정 전까지 이
계약이 열거하지 않는다. 정정은 update가 아니라 새 Attestation이 옛 ID를 supersede한다.

## Episode Pin

Pin은 저장된 장면의 identity다. `source_offer_id`는 `origin=system_offer`일 때만 필요하다. 직접
책갈피·사후 수동 기록·사진은 Offer 없이 Attestation과 Pin을 만들 수 있다.

Pin의 대표 좌표는 아이콘 앵커고, 공간 범위는 footprint다. 시각을 알 수 없는 수동 공간 메모는
시간을 추측하지 않고 `temporal_precision=unknown`으로 저장한다.

첫 시스템 Offer→Pin 저장 구현은
[결정 #77](../decisions/2026-09-01-spatial-diary-episode-pin-v0.md)을 따른다. low-motion v1 중 길이순
최대 3개만 Candidate로 다시 만들고 gap은 제외한다. Candidate와 ClaimAllowance는 저장하지 않으며,
실제 제시한 Offer부터 session cascade 아래 보존한다. Offer·Interaction·Attestation·Pin 생성은
caller-provided ID의 idempotent PUT이고, drift suspected인 증언은 공간 Pin으로 승격하지 않는다.

## 영구 저장하지 않는 것

- 자동 `WalkJournal` 요약문
- ClaimAllowance와 confidence score
- rainy/season/daypart facet
- EpisodeCandidate와 ranking score 자체
- 보수적 연속 복원 Field
- Memory Place biography 결과

사용자가 직접 확정한 제목·요약·대표 Pin은 자동 문장이 아니라 별도
[`PublishedJournalSnapshot`](published-journal-snapshot.md)으로 저장한다.

## 삭제

세션 삭제는 Capsule·Offer·Interaction·Attestation·Pin·Context·Published Snapshot을 모두
제거한다. Pin이 Memory
Place에 기여했다면 남은 세션으로 전기를 다시 계산한다. 삭제된 세션의 기여를 롤업에 남기지
않는다. 구체 보관 기간과 공유 projection은 결정 #57이 열어 둔 상태를 유지한다.
