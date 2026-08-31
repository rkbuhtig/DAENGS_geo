---
status: exploring
implementation: internal
---
# Intent planner — 단어 출현과 사용자 제약을 분리하는 정책 경계

## 결론

자연어의 `카페`라는 단어는 곧 `purpose.kind=cafe`가 아니다. extractor는 의미를 관찰할 뿐이고,
`PlannerCompiler`만 observation의 역할과 서버가 붙인 출처를 대조해 실행 가능한 gate로 승격한다.

```text
UI / structured request / LLM intent proposer
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

LLM adapter는 Place Search의 순수 import closure 밖인 `app.discovery.place_intent`에 있다. 외부
`/v2/places/search` 계약은 바뀌지 않는다.

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

## LLM proposer도 authority를 갖지 않는다

`app.discovery.place_intent`가 OpenAI Responses API의 strict Structured Outputs로 다음만 받는다.

```text
disposition = proposed | ambiguous | abstained
interpretations[]
  proposals[]
    role
    typed intent
    evidence quote + optional offset
```

Structured Outputs는 JSON 형태를 제한할 뿐 의미 정확성을 보장하지 않는다. 따라서 모델 schema에는
`observation_id`, `source`, `origin`, `locked`, `relaxable`, SQL이나 gate가 없다. 서버는 evidence
quote가 실제 원문에 있는지 검증하고, 반복 quote면 정확한 offset을 요구한 다음에만 observation
ID와 `source=llm_proposal`을 붙인다. 한 interpretation 안의 일부 evidence만 실패해도 전체를
거절한다. 필수 조건 하나를 조용히 버리고 나머지만 실행하는 것을 막기 위해서다.

서로 양립하지 않는 대안은 하나의 kind 합집합으로 합치지 않는다. 각 interpretation은 이후
독립적인 `PlannerRequest`로 컴파일할 수 있게 분리된 채 유지한다. 질문할지, 여가 시설을 제안형으로
보여줄지는 이 proposer가 아니라 후속 orchestration 정책의 책임이다.

OpenAI 호출은 `language.parse` Usage Gate 뒤에 있고 출고 기본 정책은 `deny-all`이다. 구현은
[OpenAI Structured Outputs 공식 문서](https://developers.openai.com/api/docs/guides/structured-outputs)의
Responses API `text.format=json_schema` 계약을 따른다.

## 평가 경계

실제 모델을 CI에서 호출하지 않는다. 녹화 fixture는 다음 오류 비용을 각각 계산한다.

| metric | 막으려는 실패 |
|---|---|
| `unsafe_positive_target_rate` | 부정·비유·가정·관계를 positive target으로 뒤집음 |
| `unsupported_visibility` | 미지원 semantic·필수조건·제외를 조용히 버림 |
| `evidence_span_accuracy` | 사용자가 말하지 않은 근거를 audit 근거로 사용 |
| `paraphrase_plan_equivalence` | 같은 뜻이 서로 다른 plan 입력으로 흔들림 |
| `exact_command_recall` | 명확한 장소 목적을 놓침 |

```bash
# 네트워크 없이 녹화 출력 평가
uv run python -m scripts.evaluate_place_intent

# DAENGS_LLM_PROVIDER=openai, API key, DAENGS_USAGE_POLICY=dev를 명시한 수동 실측
uv run python -m scripts.evaluate_place_intent --live
```

## 후속 순서

다음 단계는 자연어 exact-command regex가 아니다. 실제 평가 출력에서 위험 오류를 먼저 측정한 뒤,
여가 목적의 단일·복수 interpretation을 `inferred` 또는 `exploratory` 제안으로 표현하는 상위 응답
정책을 추가한다. `RULE_EXACT_COMMAND` 승격은 UI 고정 액션이나 사용자 확인처럼 출처가 확실한
경로에만 남긴다. 자동 완화와 신규 capability는 이 갈래에 포함하지 않는다.
