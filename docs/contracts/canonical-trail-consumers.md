# CanonicalTrail consumer contract

이 문서는 [결정 #84](../decisions/2026-09-03-canonical-trail-consumer-boundary.md)를 구현할 때
지켜야 할 최소 경계다. Python에서는 `CanonicalWalkComputation.trail`과 receipt 전용
`MeasurementReceiptInput`으로 드러나며 새 저장 테이블을 만들지 않는다.

## Producer

한 산책 finalize는 raw fix에 canonical acceptance를 한 번만 적용한다.

```text
CanonicalTrail [TRANSIENT, RAW-SENSITIVE]
- session_id
- dog_id
- calculation_version
- ordered Segment[]
- GapSpan[] and chain boundaries
- canonical quality evidence
- midpoint_sample one point for current Trail Context capture
```

불변식:

1. 서로 다른 consumer가 raw fix를 다시 받아 acceptance를 재구현하지 않는다.
2. Segment는 gap, jump, explicit chain boundary를 가로질러 연결되지 않는다.
3. CanonicalTrail은 DB·cache·log·message bus에 영구 기록하지 않는다.
4. accepted fix 열은 receipt 전용 입력이며 기본 consumer surface가 아니다.
5. Trail Context에는 전체 열 대신 산책 중간 시각에 가장 가까운 대표점 하나만 제공한다.
6. 동일 입력과 calculation version은 동일한 canonical 결과를 만든다.

## Consumer

각 consumer는 다음 개념을 독립적으로 소유한다.

```text
ConsumerPolicy
- consumer
- policy_version
- policy_fp

ConsumerEligibility
- status
- reason_codes[]

ConsumerProjection
- source calculation_version
- own projection/policy version
- own lifetime and deletion relation
```

정확한 enum과 reason code는 consumer 결정이 소유한다. 공통 계약은 다음만 요구한다.

- eligibility 실패를 빈 결과나 0건 관측으로 바꾸지 않는다.
- 품질 저하를 반경 확대나 끊긴 구간 연결로 보상하지 않는다.
- 다른 consumer projection을 authoritative 입력으로 사용하지 않는다.
- output에는 canonical calculation version과 자기 policy/version을 재현할 수 있는 정보가 있다.

## Current and candidate consumers

| Consumer | 상태 | purge 전 의무 |
|---|---|---|
| WalkFacts·Cellophane·Micro·Receipt·Context·Manifest | adopted mandatory | #75 트랜잭션에서 모두 seal |
| `WalkDiaryRoute` | candidate | 없음 — 별도 privacy/retention 결정 전 저장 금지 |
| `TerritorySiteEncounter` | candidate | 없음 — 점령 권위 결정 전 제품 기록 금지 |

후보가 채택되면 그 결정이 mandatory/optional 여부, 실패 처리, seal 순서와 삭제 수명을 추가한다.

## Territory claimant v0

점령 계약이 채택될 때 첫 claimant 표현은 `claiming_pet_id` 하나다.

1. v0에서는 세션의 `dog_id`와 같아야 한다.
2. 한 Encounter나 Capture를 여러 pet claim으로 복제하지 않는다.
3. pet 수는 점령력, 횟수, cooldown 혜택을 늘리지 않는다.
4. 권한 actor인 사용자 계정과 표시·상태 claimant를 같은 identity라고 가정하지 않는다.
5. projected state의 타입명은 `TerritorySiteClaimState`처럼 claimant 종류에 중립적이어야 한다.

다견 세션과 Household claimant는 이 계약의 암묵적 확장이 아니라 후속 버전이다.
