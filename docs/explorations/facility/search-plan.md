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

## deterministic purpose policy

`PurposeId`는 자연어가 아니라 UI·rule parser·향후 LLM이 선택할 안정 ID다. 현재 catalog는
`healthcare`, `pet_care`, `shopping`, `dining`, `outing`, `culture`, `lodging` 일곱 개이며,
각 ID를 현재 executor가 이해하는 canonical kind 묶음으로만 푼다. 입력 순서가 달라도 catalog
순서의 같은 plan이 나오고, 둘 이상의 목적이 6-kind 요청 경계를 넘으면 조용히 자르지 않고
거부한다. fallback인 `etc`는 명시적인 목적 후보에 자동 포함하지 않는다.

사용자가 직접 고른 목적과 system 목적은 잠기며, 추론된 목적만 `relaxable`이다. 아직 안정적인
source 공통 subtype executor가 없으므로 taxonomy code나 subtype을 조건인 것처럼 만들지 않는다.
이 계층은 자연어를 해석하지도 않는다.

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
강제한다. 단일 plan의 모양만 검사해서는 잠긴 값을 바꾼 뒤 다시 잠그는 우회를 찾을 수 없으므로,
후속 editor는 반드시 `guard_plan_transition(previous, proposed)`을 호출한다. 이 전이 guard는
잠긴 gate의 삭제와 `value/mode/origin`을 포함한 모든 변경을 거부한다.

`limit_per_kind`의 계약 상한과 실제 resolver 상한은 공통 상수 `3,000`을 사용한다. 따라서
계약상 유효한 plan이 실행기 입력 변환 단계에서 뒤늦게 실패하지 않는다. 여러 kind의 합계는
별도의 전체 예산 `5,000`으로 다시 제한한다.

## 기존 API와의 관계

`POST /v2/places/search`의 `PlaceSearchRequest`와 응답 JSON은 바뀌지 않는다. 현재 요청은 먼저
plan으로 compile되고, HTTP wrapper와 직접 plan 실행이 같은 결과를 내는 통합 테스트가 이를
고정한다.

저수준 `app.geo.contract.SearchPlan`은 의료 테이블 한 번의 공간 질의를 실행하는 계약이다.
새 `PlaceSearchPlan`은 의료·KCISA·KTO resolver를 여러 kind 그룹으로 조율하는 상위 계약이므로
둘을 억지로 합치지 않는다.

## 정적 명세와 동적 관측

capability registry에는 의미, 타입, operator, 허용 mode/origin, executor와 canonical projection
path, 현재 execution path만 둔다. 원천 지원은 `projection_sources`와 `execution_sources`로
분리한다. 전자는 각 원천 projector가 해당 evidence path를 직접 만드는지, 후자는 canonical
분류나 provenance가 붙은 effective fact를 통해 실제 executor가 읽을 수 있는지를 뜻한다.

예를 들어 주차의 `operations.parking` projection은 현재 KCISA만 직접 만들지만, ranker가 읽는
`PlaceResult.facts.parking`에는 KTO에서 보강된 effective fact도 들어올 수 있다. 그러므로 KTO를
직접 projection 지원 원천으로 가장하지 않고 execution 원천에만 선언한다. MOIS도 존재하지 않는
`mois` 별칭 대신 catalog의 실제 source id를 사용한다. projection 경로·원천과 실제 executor의
존재를 테스트로 대조해 registry와 구현이 따로 표류하지 않게 한다. coverage와 freshness는 현재
DB를 읽어야 하는 동적 값이므로 정적 registry에 박지 않는다. plan preview가 candidate bundle을
읽어 실행 결과와 source evidence 상태를 별도 축으로 계산한다.

## plan preview

`preview_search_plan()`은 선호 gate를 끈 spatial 후보 window를 먼저 얻고, 최대 1,000개를
`CandidateFactBundle`과 연결한다. plan의 gate 순서마다 다음을 계산한다.

```text
executor outcome: known_match / known_mismatch / unknown / remaining
source evidence:  known / unknown / missing / conflicted / failed / unsupported
acquisition:      not_fetched / fetched / fetch_failed / ...
```

이 축들은 합치지 않는다. 예를 들어 현재 effective `facts.parking=true`라서 ranker가 실행할 수
있더라도, KTO projector가 `operations.parking`을 직접 만들지 않으면 executor outcome은 match,
source evidence는 unsupported다. 같은 KCISA 후보의 두 원문이 주차 값에 충돌해도 effective 값을
임의로 덮지 않고 source evidence를 conflicted로 남긴다.

preview 후보 수는 최종 응답의 `limit_per_kind`와 다르다. 작은 화면 limit 때문에 데이터 분포를
한두 건으로 오판하지 않도록 1,000개 예산을 kind별로 균등 배분하고, resolver 상한에 걸린 kind는
`truncated_kinds`로 밝힌다. preview는 관측만 하며 plan을 수정하거나 검색 응답 계약에 노출되지
않는다.

다음 순서는 다음과 같다.

1. typed intent observation과 planner authority 경계 — 구현
2. 보수적인 rule extractor와 ambiguity fixture
3. 실제 planner/preview 사례를 관측한 뒤 필요한 relax 규칙만 추가
4. 마지막에 LLM observation proposer
