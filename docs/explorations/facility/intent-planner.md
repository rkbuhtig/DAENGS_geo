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
| `goal` | 사용자가 하려는 활동 또는 그 객체 | 정규화 전에는 금지 |
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

## suggestion-first orchestration

`PlaceIntentSuggestionService`가 proposer, evidence grounding, suggestion policy를 한 경로로 묶는다.
각 interpretation은 독립적인 `PlannerRequest`로 컴파일하며, 대안의 kind를 한 plan에 합치지 않는다.
이번 단계도 내부 orchestration 계약만 추가하며 외부 `/v2/places/search` 응답은 바꾸지 않는다.

```text
한 interpretation이 ready
→ status=ready, resolution=inferred, plan 1개

둘 이상의 대안 interpretation이 ready
→ status=ready, resolution=exploratory, 독립 plan 2~3개

일부 대안만 ready
→ ready plan은 제안
→ 실패한 대안은 rejected PlannerResult로 보존

모두 실패
→ 제한된 여가 soft fallback 또는 clarification/unsupported
```

`status`는 실행 가능한 plan의 존재 여부이고, `resolution`은 사용자 의도를 직접 확정했는지 또는
탐색 제안인지다. 둘을 한 enum에 섞지 않는다. LLM 경로는 사용자 확인을 받지 않았으므로
`explicit`을 만들지 않고 `inferred` 또는 `exploratory`만 만든다.

제품 fallback은 일반 자연어 규칙이 아니다. 직접 실행 가능한 target이 없고 다음 allowlist만 있을
때 별도의 `rule_inference` observation을 만들어 inferred plan을 제안한다.

```text
soft place role
- preference / analogy / hypothetical

soft semantic concept
- semantic.atmosphere
- semantic.comfort
- semantic.cozy
- semantic.quiet
```

장소 cue가 있으면 그 장소를 하나의 탐색 제안으로 사용한다. soft semantic만 있으면 제품이 고정한
`dining`, `outing`, `culture` 세 그룹을 별도 plan으로 제안한다. 원래 interpretation은 rejected에
남으므로 `quiet`나 `atmosphere`가 실제 데이터로 확인된 것처럼 보이지 않는다. 함께 제안된 parking
preference는 fallback plan에도 보존한다.

다음은 fallback을 열지 않는다.

```text
required_condition / excluded / negated / relational
allowlist 밖 semantic concept
hospital / pharmacy / healthcare의 soft 언급
장소 target 없이 parking preference만 있는 경우
```

따라서 `주차 필수`, `카페 제외`, `병원이나 갈까`를 여가 기본 제안으로 조용히 약화하지 않는다.
모델 evidence가 원문에 고정되지 않을 때도 service는 plan을 만들지 않고
`intent_evidence_invalid` clarification으로 닫는다.

## interpretation normalization과 검색 가설

LLM interpretation 하나에 들어온 의미를 평평한 태그 AND로 컴파일하지 않는다.
`build_search_hypotheses()`가 evidence grounding 뒤, planner 앞에서 제품 catalog에 선언된 관계만
적용해 다음 계약으로 정규화한다.

```text
SearchHypothesisSet
├─ common[]              모든 대안에 유지할 조건·제외·선호
├─ hypotheses[]          서로 독립적인 target 가설
├─ modifiers[]           실행 전까지 보존할 rank-only 신호
├─ unresolved_facets[]   사용자 선택이 더 필요한 차원
└─ relation_receipts[]   적용한 고정 정책과 입력 observation id
```

현재 catalog는 의도 판단과 데이터 보장을 구분하기 위한 최소 관계만 갖는다.

```text
pet_shop + shopping purpose
→ 더 구체적인 pet_shop target만 유지

activity.buy + object.dog_toy
→ pet_shop 검색 가설
→ 장난감 재고가 있다는 보장은 만들지 않음

activity.play
→ dedicated play / outdoor play / stay together의 독립 가설
→ 사용자가 어느 하나를 원한다고 확정하지 않음

semantic.quiet
→ rank_only_unavailable modifier

semantic.cheap
→ travel distance / pet fee / admission / product price 중
  비용 차원을 고르기 전까지 unresolved
```

공통 필수조건은 각 branch 안에 복제 저장하지 않고 `common`에 한 번 보존한다. 후속 executor는
`planner_observations()`를 통해서만 target과 common을 조립한다. 따라서 `play + 주차 필수`가
세 가지 play 가설로 나뉘어도 현재 미지원인 hard parking은 세 가설을 모두 막는다.

`PlaceIntentSuggestionTrace.normalized`에서 이 내부 계약을 관찰할 수 있지만, 이번 단계는
`/v2/places/search`나 실제 ranker를 바꾸지 않는다. 가설별 사용자 표시·소량 실행은 다음 단계의
책임이다.

## search lens 실행과 표시 계약

`compile_search_lenses()`는 정규화 가설을 planner에 연결하되 사용자에게는 안정적인 lens로
표현한다. 기술적인 interpretation key나 모델 confidence 대신 다음만 노출한다.

```text
TargetSearchLens
├─ display_label           #놀기 / #산책·야외 / #펫샵
├─ mapping_scope           direct / broad / product_fallback
├─ availability            executable / blocked / needs_selection
├─ support_note            현재 분류가 보장하는 범위
├─ candidate               planner result와 plan
├─ confirmable_targets     후속 사용자 선택이 승격할 target
├─ modifier_ids            보존했지만 아직 적용하지 못한 선호
├─ unresolved_facet_ids    선택 전에는 실행을 막는 차원
└─ unsupported_signals     planner issue와 미지원 modifier 영수증
```

가설 target과 `common`은 반드시 `SearchHypothesisSet.planner_observations()`로 조립한 뒤
`compile_intent_plan()`을 통과한다. 공통 hard condition이 막은 lens는 결과를 검색하지 않고
`blocked`로 남는다. target plan이 준비됐더라도 필수 cost facet이 풀리지 않았으면
`needs_selection`이며 역시 실행하지 않는다.

`semantic.quiet`는 조금 다르다. 조용함이 적용됐다고 말하지 않고 `deferred` modifier와 명시적인
support note를 붙인 채 제품 fallback lens의 소량 결과를 먼저 보여준다. 이 결과는 조용함 순위가
아니며, 화면에도 그 사실을 그대로 쓴다.

개발 lab은 executable lens마다 PostGIS 검색을 실행하되 한 lens 전체에서 2~4곳만 round-robin으로
남긴다. 종류가 두 개인 purpose도 한 선반을 독점하지 않으며, lens끼리 점수 하나로 섞지 않는다.
이 경계 역시 외부 `/v2/places/search` 계약은 변경하지 않는다.

## 후속 순서

다음 단계는 사용자가 lens를 선택·수정했을 때 `confirmable_targets`만 `user_confirmed`로 다시
관찰해 explicit lock으로 승격하는 경계다. 장소 마커 클릭은 탐색 행동일 뿐 confirmation으로
취급하지 않는다. 자연어 exact-command regex, 자동 완화, 신규 capability는 여전히 이 갈래에
포함하지 않는다.
