---
status: exploring
implementation: internal
---
# Intent planner — 단어 출현과 사용자 제약을 분리하는 정책 경계

## 결론

자연어의 `카페`라는 단어는 곧 `purpose.kind=cafe`가 아니다. extractor는 의미를 관찰할 뿐이고,
`PlannerCompiler`만 observation의 역할과 서버가 붙인 출처를 대조해 실행 가능한 gate로 승격한다.

```text
UI / structured request / future rule or LLM extractor
                         │
                         ▼
                  IntentProposal[]
             concept + role + evidence
                         │ server adapter
                         ▼
                 IntentObservation[]
                 + server-owned source
                         │
                         ▼
                  PlannerCompiler
        authority / capability / blocking policy
                         │
                         ▼
                  PlannerResult
       plan | unsupported | clarification | not_applied
                         │
                         ▼
              PlanGuard → PlanPreview
```

이번 단계에는 raw 한국어 parser와 LLM이 없다. 외부 `/v2/places/search` 계약도 바뀌지 않는다.

## observation은 명령이 아니다

`kind`, `purpose`, boolean capability, 아직 지원하지 않는 semantic concept를 서로 다른 typed
observation으로 받는다. 공통 role은 다음과 같다.

| role | 의미 | 자동 gate 승격 |
|---|---|---|
| `required_target` | 직접 찾는 장소 대상 | 권한·executor가 있을 때만 |
| `required_condition` | 반드시 충족할 사실 조건 | filter executor가 있을 때만 |
| `preference` | 있으면 좋은 조건 | prefer executor가 있을 때만 |
| `analogy` | 비유·예시 | 금지 |
| `excluded` | 제외 요구 | exclude executor가 없으면 blocking |
| `negated` | 부정된 언급 | 적용하지 않고 기록 |
| `hypothetical` | 가정·가능성 | 금지 |
| `relational` | 주변·내부 시설 같은 관계 | 금지 |

따라서 `카페 같은 분위기`의 cafe observation이 있어도 role이 `analogy`면 kind gate가 생기지
않는다. `병원 갈 정도는 아니야`의 hospital도 `negated`로 기록될 뿐 후보가 되지 않는다.

## source는 서버가 붙이는 권한 봉투다

extractor나 향후 LLM tool이 보는 `IntentProposal` schema에는 `source`, `origin`, `locked` 필드가
아예 없다. adapter가 `observe_intent(proposal, source)`로 호출 경로의 source를 붙이고 compiler가
다음 표를 적용한다.

| observation source | purpose gate | parking preference |
|---|---|---|
| structured request / UI / user confirmed / exact command | `user_explicit + locked` | `user_preference` |
| rule inference / LLM proposal | `inferred + relaxable` | `inferred` |
| context | 목적 filter 생성 금지 | `context + prefer` |

명시 목적이 하나라도 있으면 inferred 목적은 후보군을 넓힐 수 없다. inferred observation은
`shadowed_by_explicit_target`으로 남는다. evidence 원문은 plan trace에 복사하지 않고 observation
ID만 연결한다.

## unsupported는 강도에 따라 실행을 막는다

미지원 선호와 미지원 필수조건을 같은 경고로 취급하지 않는다.

```text
"조용하면 좋겠어" + cafe
→ cafe plan은 실행 가능
→ semantic.quiet는 non-blocking unsupported

"주차 필수" + cafe
→ hard parking executor 없음
→ blocking unsupported
→ plan을 만들지 않음

"식당은 제외" + cafe
→ kind exclusion executor 없음
→ blocking unsupported
→ plan을 만들지 않음
```

`PlannerResult` 자체도 ready plan과 blocking issue를 함께 만들 수 없도록 검증한다. 후보 kind가
6개를 넘거나 전체 결과 예산 5,000을 넘을 때도 조용히 자르지 않고 clarification으로 멈춘다.

## 후속 순서

다음 PR에서만 보수적인 한국어 rule extractor를 추가한다. 전체 문장의 일부 단어를 검색하지
않고, 허용된 명령형 문법과 비유·부정·가정·관계 marker를 분리하며 애매하면 observation 또는
clarification까지만 만든다. 그 parser도 plan이나 lock을 직접 만들지 못한다.
