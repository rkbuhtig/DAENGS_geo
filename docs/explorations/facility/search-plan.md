---
status: exploring
implementation: internal
---
# Place SearchPlan — AI보다 먼저 고정하는 검색 정책 계약

## 결론

설계의 중심은 AI가 아니라 `PlaceSearchPlan`이다. UI, 규칙 기반 planner, 향후 LLM tool이
같은 plan을 만들 수 있고, 같은 plan은 항상 같은 결정론적 executor를 탄다. LLM은 SQL이나
원천 공공데이터 필드를 직접 다루지 않는다.

```text
structured request / purpose policy / future AI tool
                         │
                         ▼
                  PlaceSearchPlan
             ┌───────────┴───────────┐
             │                       │
 PlaceSpatialConstraint         SearchGate[]
 lat/lng/radius                 stable capability id
             │                       │
             └──────── PlanGuard ────┘
                         │
                         ▼
              existing deterministic resolvers
```

공간 반경은 목적이나 사실 조건과 섞지 않는다. `spatial`은 PostGIS 후보 경계이고,
`purpose.kind`는 어떤 종류의 독립 후보군을 열지 정한다. 반경을 넓히는 것과 목적 kind를
확장하는 것은 서로 다른 trace와 완화 규칙을 가져야 한다.

## 이번 PR에서 실행 가능한 capability

registry에는 이름이 그럴듯한 조건이 아니라 **현재 executor가 있는 것만** 선언한다.

| capability | mode | unknown | 실행 단계 | 실제 동작 |
|---|---|---|---|---|
| `purpose.kind` | `filter` | `exclude` | candidate | canonical kind별 resolver 후보군 생성 |
| `operations.parking` | `prefer` | `keep` | ranking | 같은 500m 거리 band 안에서 주차 가능 우선 |

주차 hard filter는 아직 없다. 따라서 guard는 `operations.parking + filter`,
`unknown=exclude`, `value=false`를 모두 거부한다. 실행기가 없는 강도를 AI가 tool call로
요청해도 정책으로 승격되지 않는다.

`pet_access.indoor_zone_hint`, `semantic.quiet`도 아직 registry에 없다. 전자는 source hint를
새 rank feature로 연결한 뒤 `prefer`까지만 열어야 하고, 후자는 현재 조용함 evidence 자체가
없다.

## gate 정책

각 gate는 다음을 기록한다.

```text
capability_id / mode / operator / value / unknown_policy
origin / locked / relaxable
```

- `off`: 실행하지 않음
- `prefer`: 후보를 제거하지 않고 순위만 바꿈
- `filter`: 조건에 따른 후보 제외
- `keep/separate/exclude`: 미상값 처리. mode와 별도 축
- `origin`: 사용자 명시, 사용자 선호, profile, context, inferred, system
- `locked`: 후속 editor가 변경할 수 없음
- `relaxable`: 결정론적 완화 대상인지 여부

사용자가 직접 넘긴 kind filter는 `user_explicit + locked`다. 향후 목적 정책이 만든 kind
후보군은 `inferred + relaxable`로 만들 수 있다. profile/system gate는 guard가 잠금을
강제한다.

## 기존 API와의 관계

`POST /v2/places/search`의 `PlaceSearchRequest`와 응답 JSON은 바뀌지 않는다. 현재 요청은 먼저
plan으로 compile되고, HTTP wrapper와 직접 plan 실행이 같은 결과를 내는 통합 테스트가 이를
고정한다.

저수준 `app.geo.contract.SearchPlan`은 의료 테이블 한 번의 공간 질의를 실행하는 계약이다.
새 `PlaceSearchPlan`은 의료·KCISA·KTO resolver를 여러 kind 그룹으로 조율하는 상위 계약이므로
둘을 억지로 합치지 않는다.

## 정적 명세와 동적 관측

capability registry에는 의미, 타입, operator, 허용 mode/origin, 지원 원천, executor와 canonical
projection path, 현재 execution path만 둔다. 예를 들어 주차는 `operations.parking`으로
projection되고 현재 `PlaceResult.facts.parking`을 ranker가 읽는다. 두 경로와 실제 executor의
존재를 테스트로 대조해 registry와 구현이 따로 표류하지 않게 한다. coverage와 freshness는 현재
DB를 읽어야 하는 동적 값이므로 정적 registry에 박지 않는다. 후속 preview가 candidate bundle을
읽어 source별 known/mismatch/unknown을 계산한다.

다음 순서는 다음과 같다.

1. deterministic purpose policy: 목적 → kind/subtype/taxonomy 후보
2. plan preview: gate별 match/mismatch/unknown과 남은 후보 수
3. 제한된 relax 순서와 trace
4. rule-based planner
5. 마지막에 LLM tool editor
