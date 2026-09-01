---
status: adopted
decision: 81
adopted_at: 2026-09-01
---
# 공간적 부재는 drift 미의심 평가가 있을 때만 말한다

Memory Place biography의 `not_observed`는 단순히 drift가 `suspected`가 아니라는 이유로 허용하지
않는다. 부정적 공간 주장은 해당 산책의 MeasurementReceipt에 평가 방법이 있는
`drift_assessment=not_suspected`가 기록됐을 때만 허용한다.

## 양성 관측과 부정 관측의 비대칭

한 장소와 겹치는 slow observation이 실제로 남아 있으면 drift가 `not_assessed` 또는
`insufficient_evidence`여도 `observed`를 유지할 수 있다. 위치는 계속 approximate이며, 이것은
정확한 장소나 원인을 확정하는 주장이 아니다.

반대로 slow observation이 없다는 사실을 장소에서의 사건 부재로 바꾸려면 적극적인 자격이
필요하다.

```text
not_suspected + assessment method
→ negative_spatial_claim.eligible = true
→ clear exposure + capability + zero observation일 때 not_observed

not_assessed | insufficient_evidence
→ negative_spatial_claim.eligible = false
→ zero observation은 drift 이유가 있는 unjudgeable

suspected
→ 양성·부정 공간 관측 모두 unjudgeable
```

`suspected가 아님`과 `drift가 의심되지 않는다고 평가함`은 서로 다른 증거다. 전자는 검사를 하지
않은 상태를 포함하지만 후자는 평가 방법을 가진 결과다.

## 계약과 재현

산책별 biography reading은 `NegativeSpatialClaimAllowance`를 반환한다.

```text
policy_version
eligible
macro_exposure
capability
drift_assessment
blocking_reasons
```

`eligible`은 drift만 통과했다는 뜻이 아니다. clear macro exposure, 현재 observation capability,
`not_suspected` drift 평가가 모두 있을 때만 참이다. `blocking_reasons`는 노출·capability·drift 중
실패한 모든 gate를 보존한다. 차단된 부정 주장은 `spatial_drift_not_assessed`,
`spatial_drift_insufficient_evidence`, `spatial_drift_suspected` 중 실제 receipt 상태와 일치하는
이유를 노출한다. 부정적 공간 주장 정책은 독립된 v1으로 고정하고, biography의 기존
`observation_policy_version`은 판정 변화에 맞춰 2로 올린다.

기존 Capsule의 기본값 `not_assessed`를 소급해 `not_suspected`로 바꾸지 않는다. 이 결정은 drift
판정기를 새로 만들지 않는다. 따라서 평가기가 조립되기 전 생산 데이터에서는 양성 관측은 남지만
공간적 `not_observed`는 보수적으로 `unjudgeable`이다.

이 결정은 [Memory Place v0 결정 #78](2026-09-01-spatial-diary-memory-place-v0.md)의
“drift suspected가 아니면 `not_observed` 가능” 조건을 대체한다.
