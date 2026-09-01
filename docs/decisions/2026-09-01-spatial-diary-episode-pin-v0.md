---
status: adopted
decision: 77
adopted_at: 2026-09-01
---
# low-motion 후보는 실제 제시본과 사용자 증언을 거쳐야 공간 일기 Pin이 된다

결정 #74는 Candidate·Offer·Interaction·Attestation·Pin의 수명을 분리했고, #75는 그 입력인
Micro Observation과 MeasurementReceipt를 Capsule에 봉인했다. #76은 Pin 없이 조건별 공간 배경을
읽는 첫 View를 열었다. 이번 결정은 그 재료 한 조각이 사용자 기억이 되어 같은 View에 나타나는
첫 제품 한 바퀴를 닫는다.

```text
low_motion Micro Observation [FROZEN MATERIAL]
→ EpisodeCandidate + ClaimAllowance [DERIVED]
→ EpisodeOfferSnapshot [FROZEN WHEN SHOWN]
→ OfferInteraction [APPEND-ONLY, NOT TESTIMONY]
→ WalkAttestation [APPEND-ONLY USER TESTIMONY]
→ EpisodePin [STABLE IDENTITY, memory_action=save]
→ SpatialDiaryView EntrySelector [PIN OVERLAY ONLY]
```

## Candidate policy v1

한 산책의 `low_motion generation=1` capability가 있을 때 `observation_version=1`의 `slow`만
읽는다. `gap`은 관측이 없던 시간이므로 후보로 만들지 않는다. `duration_s` 내림차순,
`observation_index` 오름차순으로 최대 3개를 반환한다. 이 순위는 중요도나 행동 확률이 아니라
종료 직후 검토량을 제한하는 제시 순서다.

```text
candidate_policy_version = 1
max candidates per walk = 3
event_at = observed low-motion window midpoint
representative_point = stored observation centre
footprint radius = max(5m, span_m + accuracy_p50_m)
```

5km보다 큰 footprint가 필요한 행은 현재 지도 사건 계약으로 표현할 수 없으므로 후보에서
제외한다. 저장하는 evidence는 duration·path·net·span·fix count·accuracy p50·break 인접 여부·
route offset이다. Candidate 자체와 ranking score는 저장하지 않는다.

`천천히 움직임`은 탐색·배변·마킹·교류·견주 정지를 뜻하지 않는다. Offer prompt도 이 관측
언어만 사용하고, 의미는 사용자가 claims로 답하기 전까지 만들지 않는다.

## Claim policy v1

low-motion window의 중앙 시각은 직접 관측한 정확한 사건 시각이 아니므로 temporal은
`approximate`다. 현재 휴대폰만으로 drift 부재를 입증하지 못하므로 spatial도 기본
`approximate`다. MeasurementReceipt의 drift가 `suspected`이면 spatial은 `unsupported`가 되어
검토·dismiss 증언은 가능하지만 좌표 Pin 저장은 거부한다. interpretation은 항상
`attestation_required`다.

```text
claim_policy_version = 1
temporal       approximate
spatial        approximate | unsupported when drift suspected
interpretation attestation_required
```

ClaimAllowance는 현재 영수증과 정책으로 다시 만드는 결과이며 영구 테이블이 아니다. Offer에는
사용자가 본 정책 버전과 evidence·footprint·prompt를 동결한다.

## 실제 제시와 사용자 응답

생성 명령은 호출자가 경로 ID를 제공하는 idempotent `PUT`이다. 같은 ID와 같은 내용의 재전송은
기존 불변 객체를 반환하고, 다른 내용과 충돌하면 409다.

```text
GET /spatial-diary/walks/{session_id}/candidates
GET /spatial-diary/walks/{session_id}/offers
PUT /spatial-diary/offers/{offer_id}
GET /spatial-diary/offers/{offer_id}
PUT /spatial-diary/offers/{offer_id}/interactions/{interaction_id}
PUT /spatial-diary/offers/{offer_id}/attestations/{attestation_id}
```

Candidate policy 세대 하나에서는 source observation 하나당 immutable Offer도 하나다. 같은
후보를 새 ID로 반복 제시해 중복 Pin을 만드는 경로를 열지 않는다.
산책별 Offer 목록은 interaction·Attestation·Pin 상태를 함께 반환해 앱이 재시작돼도 미응답
검토를 이어갈 수 있게 한다. Candidate 목록은 여전히 현재 정책의 재계산 결과다.

v0의 사용자 interaction은 `viewed|dismissed`다. `expired`는 계약과 DB에는 있지만 시스템 작업이
아직 없으므로 공개 입력으로 받지 않는다. dismissed/expired Offer에는 Attestation을 붙일 수
없다. interaction 종류 하나는 Offer당 한 번만 기록해 caller가 새 ID를 만들어 같은 상태를
무제한 누적할 수 없게 한다. 무응답에는 Attestation이 없고, 사용자가 `uncertain`을 제출한
경우에만 증언이 생긴다.

Attestation은 `review_disposition`, versioned `claims(subject_role, meaning_code)`,
`memory_action`을 분리한다. `save`에는 caller가 제공한 `pin_id` 하나가 필요하고, `dismiss`에는
Pin이 없다. rejected는 positive claim이나 save를 가질 수 없다. Offer 하나의 첫 구현은 증언
하나만 받으며 superseding 정정과 Offer 없는 수동 Pin 경로는 후속 범위다.

Offer·Interaction·Attestation·Pin은 모두 `walk_session` 삭제 cascade를 탄다. Pin은 Offer의
approximate 시각·대표점·footprint를 그대로 계승하며, 대표점은 아이콘 앵커일 뿐 정확 좌표
주장이 아니다.

한 View 응답은 최대 2,000 Pin이며, v0의 후보·Offer 유일성 때문에 현재 최대치는 선택 Capsule
400개 × 산책당 3개 = 1,200개다. 후속 수동 Pin 경로가 이 전제를 바꾸면 pagination이나 tile
overlay를 먼저 결정한다.

## SpatialDiaryView overlay

결정 #76의 Walk Selector와 Field 분모는 바꾸지 않는다. 선택된 Capsule의 Pin만 불러온 뒤
Entry Selector를 적용한다.

```text
EntrySelector.subject_roles  claims 중 하나와 일치
EntrySelector.meaning_codes  claims 중 하나와 일치
두 축을 함께 쓰면 같은 claim 안에서 AND
```

Entry filter가 있는 산책만 Cellophane cohort에 남기는 것은 금지한다. 응답의 `pins`에는 안정 Pin,
review disposition, claims가 들어가고 `receipt.pin_count`가 같은 개수를 보인다. Pin 상세가 실제로
제시된 문장을 필요로 하면 `source_offer_id`로 immutable Offer를 읽는다.

모든 공개 읽기·쓰기는 실제 인증 계층이 주입한 principal의 `dog_ids`로 소유권을 확인한다.
fake OwnerProfile을 인증으로 쓰지 않으며 인증 조립 전에는 503, 타 견주 리소스는 404다.

## 이 결정이 정하지 않는 것

- 행동 vocabulary의 제품 목록과 아이콘
- superseding Attestation과 기존 Pin 정정 규칙
- in-walk bookmark·사후 수동·사진 Pin API
- EventContextSnapshot과 사진·사용자 자유 메모
- 자동 WalkJournal 문장과 PublishedJournalSnapshot
- Memory Place 형성·biography·비/비 없음 비교

다음 PR은 서로 다른 산책의 Pin을 반복 장소로 묶기 전에 macro exposure와 capability-aware
judgeability를 먼저 계산하고, 안정 Memory Place identity와 첫 조건 비교를 연다.
