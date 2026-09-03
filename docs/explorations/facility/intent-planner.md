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

`app.discovery.place_intent`의 OpenAI Responses·Gemini Interactions 어댑터는 같은 authority-free
출력 계약으로 다음만 받는다.

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

두 실제 모델 호출은 모두 `language.parse` Usage Gate 뒤에 있고 출고 기본 정책은 `deny-all`이다.
OpenAI 어댑터는 [OpenAI Structured Outputs 공식 문서](https://developers.openai.com/api/docs/guides/structured-outputs)의
Responses API `text.format=json_schema`를, Gemini 어댑터는 Interactions API의 JSON schema 응답을
각각 같은 내부 계약으로 정규화한다. 현재 `/dev/place-intent/*` lab은 Gemini만 조립하고,
`scripts.evaluate_place_intent --live`는 `--provider gemini|openai`로 둘 중 하나를 명시적으로 고른다.
`DAENGS_LLM_PROVIDER`와 해당 API key를 진입점에 맞게 명시하지 않으면 lab은 503으로, evaluator는
실제 호출 전에 닫힌다.

## 평가 경계

실제 모델을 CI에서 호출하지 않는다. 기존 13개 녹화 fixture는 회귀 검사용으로 유지하고,
`open_discovery_cases.json`은 실제 모델을 정량 평가하기 위한 50개 정답 코퍼스다. 코퍼스는
`delegated_open`, `explicit_directed`, `mixed_delegation`, `affective_ambiguous`, `role_safety`
다섯 범주를 10개씩 담고, 프롬프트를 조정해도 되는 calibration 30개와 최종 확인 전에는 열지 않는
holdout 20개로 고정한다. calibration 안에는 범주별 2개씩 뽑은 stability probe 10개도 고정한다.
모델 출력은 코퍼스와 분리된 recording에 저장한다.

각 case는 LLM의 의미 정답과 별도로 제품 진행 결과를 고정한다. `results_now`와
`results_with_refinement`는 후보를 먼저 보여주는 정보 제공 경로, `clarification_only`는 검색 전에
질문이 필요한 경로, `safe_no_search`는 부정·필수조건처럼 임의 완화하면 안 되는 경로다. 이 구분으로
intent가 맞아도 실제 lens가 하나도 실행되지 않는 회귀를 별도로 잡는다. 여기서 결과 제공 여부는
순수 planning pipeline이 실행 가능한 lens를 만들었는지를 뜻한다. DB 후보 수·표시 결과 수·검색 품질은
이 준비 지표에 섞지 않고 녹화 출력이 고정된 뒤 별도의 실제 검색 평가 단계에서 측정한다.

평가 준비 단계에서는 코퍼스·실행기·지표만 고정한다. 이 단계의 코드와 fixture만으로 Gemini 품질이
좋거나 나쁘다는 결론을 내리지 않는다. 실제 실측은 별도 평가 단계에서 calibration을 먼저 반복 실행한
후, 변경을 동결하고 holdout을 한 번 평가한다.

첫 Gemini 3.1 Flash-Lite calibration과 반복 결과는
[2026-09-02 연구 기록](../../research/2026-09-02-place-intent-gemini-calibration.md)에 남긴다. 이 baseline은
prompt/schema 수정 대상을 고르는 calibration이며 holdout 판정이나 제품 품질 임계값이 아니다.
[후속 calibration](../../research/2026-09-02-place-intent-gemini-calibration-v3.md)은 mixed delegation과
role/safety 경계를 수정하고 같은 corpus로 재측정한 결과다. 최종 계약은 holdout을 열기 전에 더 이상
calibration에 맞추지 않는 동결 후보로 둔다.
[최초 holdout](../../research/2026-09-02-place-intent-gemini-holdout.md)은 이 계약을 바꾸지 않고 20건을
한 번 실호출했다. 정보 제공 recall은 `100%`였지만 contract valid output `95%`, product outcome
accuracy `90%`, inappropriate search `20%`로 calibration보다 낮았다. 이 holdout을 본 뒤 기존
prompt/schema나 gold를 소급 수정하지 않으며, 후속 보정에는 겹치지 않는 새 holdout이 필요하다.

평가기는 다음 오류 비용을 각각 계산한다.
전체 평균과 함께 같은 지표를 category별로 다시 계산해 특정 문장군의 실패가 aggregate에 숨지 않게 한다.

| metric | 막으려는 실패 |
|---|---|
| `contract_valid_output_rate` | provider 응답이 intent 계약 위반으로 평가 전체를 중단시킴 |
| `invalid_output_rate` | 구조화 응답은 왔지만 authority-free intent로 검증할 수 없음 |
| `unsafe_positive_target_rate` | 부정·비유·가정·관계를 positive target으로 뒤집음 |
| `unsupported_visibility` | 미지원 semantic·필수조건·제외를 조용히 버림 |
| `evidence_span_accuracy` | 사용자가 말하지 않은 근거를 audit 근거로 사용 |
| `paraphrase_plan_equivalence` | 같은 뜻이 서로 다른 plan 입력으로 흔들림 |
| `exact_command_recall` | 명확한 장소 목적을 놓침 |
| `search_mode_accuracy` | 위임형 탐색과 목적 지정 검색을 뒤집음 |
| `open_discovery_precision/recall/f1` | open discovery를 과잉 또는 과소 선언 |
| `explicit_target_open_discovery_false_positive_rate` | 명시적 목적을 모델에게 다시 위임해 버림 |
| `grounded_output_rate` | 출력 전체가 실제 사용자 원문에 근거하는지 |
| `open_discovery_grounding_rate` | open discovery 선언의 위임 근거가 원문에 있는지 |
| `search_mode_stability` | 동일 입력 반복 호출에서 검색 모드가 흔들림 |
| `semantic_output_stability` | 동일 입력 반복 호출에서 intent·role 의미가 흔들림 |
| `product_outcome_accuracy` | 의미는 맞지만 제품이 기대한 검색 진행 상태를 만들지 못함 |
| `information_delivery_precision/recall` | 결과를 줘야 할 때 질문만 하거나, 검색하면 안 될 때 결과를 냄 |
| `inappropriate_search_rate` | clarification/safe-no-search 문장에서 임의 검색을 실행 |
| `product_outcome_stability` | 동일 입력 반복 호출에서 실제 결과 제공 여부가 흔들림 |

해당 범주에 positive 분모가 없으면 precision·recall을 성공 `1.0`으로 만들지 않고 JSON `null`로
기록한다. category별 표에서 `N/A`와 완전 성공을 혼동하지 않기 위해서다.
반복 안정성 세 지표도 repeat가 2 미만이면 비교 대상이 없으므로 `null`이다.

```bash
# 네트워크 없이 녹화 출력 평가
uv run python -m scripts.evaluate_place_intent

# Gemini calibration 30개를 1회 호출하고 원출력과 report를 따로 보존
# DAENGS_LLM_PROVIDER=gemini, DAENGS_GEMINI_API_KEY,
# DAENGS_USAGE_POLICY=dev를 먼저 명시한다.
uv run python -m scripts.evaluate_place_intent \
  --fixture tests/fixtures/place_intent/open_discovery_cases.json \
  --split calibration --provider gemini --repeat 1 --live \
  --recording-out outputs/place-intent-gemini-calibration.json \
  --report-out outputs/place-intent-gemini-calibration-report.json

# 별도 Usage Gate 시간창에서 범주별 2개인 stability probe 10개를 3회 측정
uv run python -m scripts.evaluate_place_intent \
  --fixture tests/fixtures/place_intent/open_discovery_cases.json \
  --split calibration --stability-probe --provider gemini --repeat 3 --live \
  --recording-out outputs/place-intent-gemini-stability.json \
  --report-out outputs/place-intent-gemini-stability-report.json

# 외부 호출 없이 동일 코퍼스와 recording으로 report 재현
uv run python -m scripts.evaluate_place_intent \
  --fixture tests/fixtures/place_intent/open_discovery_cases.json \
  --split calibration \
  --recording-in outputs/place-intent-gemini-calibration.json

# 중간 provider 장애로 incomplete recording이 남았으면 이미 끝난 case는 다시 호출하지 않는다.
uv run python -m scripts.evaluate_place_intent \
  --fixture tests/fixtures/place_intent/open_discovery_cases.json \
  --split calibration --provider gemini --repeat 1 \
  --resume outputs/place-intent-gemini-calibration.json
```

recording에는 provider, model, 생성·갱신 시각, 선택된 코퍼스·prompt·output schema의 SHA-256,
명시적인 generation config, 목표 반복 수, 완료 여부와 반복별 구조화 출력만 들어간다. API key는
저장하지 않는다. 각 case가 끝날 때 원자적으로 checkpoint하므로 중간 실패 뒤 `--resume`할 수 있고,
digest·provider·model·prompt·schema·generation config가 달라지면 재개를 거부한다. incomplete recording은
평가 입력으로 사용할 수 없다. 기본 `dev` Usage Gate는 `language.parse`를 시간창당 30회로 제한하며
evaluator는 남은 호출 수가 이를 넘으면 provider 호출 전에 거절한다. 그러므로 calibration 1회와
stability probe 3회는 같은 시간창에 연달아 실행하지 않는다.

provider가 응답했지만 intent 계약 검증에 실패한 case는 `invalid_output`과 해당 raw structured output을
완료된 평가 결과로 기록하고 다음 case로 진행한다. 이 raw output 보존은 고정된 합성 평가 문장에만
사용하며 운영 사용자 발화 로그 계약으로 승격하지 않는다. 반대로 HTTP 오류·timeout처럼 응답 자체를
신뢰할 수 없는 provider 장애는 case를 완료 처리하지 않고 실행을 중단한다. 이후 `--resume`하면 마지막
checkpoint 다음 case부터 다시 시작한다. v2 partial recording은 읽을 수 있지만 다음 checkpoint부터
failure-aware v3로 기록한다.

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
- semantic.dog_interest
```

장소 cue가 있으면 그 장소를 하나의 탐색 제안으로 사용한다. soft semantic만 있으면 제품이 고정한
`dining`, `outing`, `culture` 세 그룹을 별도 plan으로 제안한다. 원래 interpretation은 rejected에
남으므로 `quiet`나 `atmosphere`가 실제 데이터로 확인된 것처럼 보이지 않는다. 함께 제안된 parking
preference는 fallback plan에도 보존한다.
장소 target 없는 parking preference도 같은 세 방향을 먼저 보여주되, 주차 가능이 확인된 결과라고
표시하지 않는다. `semantic.dog_interest` 역시 강아지 선호를 판정할 evidence/ranker가 없다는 신호를
보존한 채 넓은 결과를 먼저 보여준다.

다음은 fallback을 열지 않는다.

```text
required_condition / excluded / negated / relational
allowlist 밖 semantic concept
hospital / pharmacy / healthcare의 soft 언급
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
→ 이미 장소 target이 있으면 그 target을 pet_shop으로 넓히지 않고 구매 목적 modifier로 보존
→ hypothetical / analogy / relational 역할에서는 positive target을 만들지 않음

activity.play
→ dedicated play / outdoor play / stay together의 독립 가설
→ 사용자가 어느 하나를 원한다고 확정하지 않음

semantic.quiet
→ rank_only_unavailable modifier

semantic.dog_interest
→ rank_only_unavailable modifier
→ 강아지가 좋아한다고 확인된 장소라는 보장은 만들지 않음

semantic.cheap
→ travel distance / pet fee / admission / product price 중
  비용 차원을 unresolved facet으로 보존
→ preference이면 넓은 결과를 먼저 보여주고 비용 차원을 함께 질문
→ 필수 역할이면 비용 차원을 고르기 전까지 실행 차단
→ excluded / negated 역할은 positive 비용 facet으로 뒤집지 않음
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

`SearchSignalLens.required`는 같은 modifier라도 필수 요구와 선택적 선호를 구분한다. 이를
`deferred`라고 표시하는 것은 현재 executor가 없다는 뜻이지, 필수 요구를 선택적 선호로 낮춘다는
뜻이 아니다.

가설 target과 `common`은 반드시 `SearchHypothesisSet.planner_observations()`로 조립한 뒤
`compile_intent_plan()`을 통과한다. 공통 hard condition이 막은 lens는 결과를 검색하지 않고
`blocked`로 남는다. target plan이 준비됐더라도 필수 cost facet이 풀리지 않았으면
`needs_selection`이며 역시 실행하지 않는다.

`semantic.quiet`는 조금 다르다. 조용함이 적용됐다고 말하지 않고 `deferred` modifier와 명시적인
support note를 붙인 채 제품 fallback lens의 소량 결과를 먼저 보여준다. 이 결과는 조용함 순위가
아니며, 화면에도 그 사실을 그대로 쓴다.

fallback lens도 interpretation 경계를 넘지 않는다. 후보 key에 대응하는 hypothesis set의 modifier와
facet만 연결하며, 다른 대안 해석의 필수조건 때문에 현재 후보를 막거나 설명을 바꾸지 않는다.

개발 lab은 executable lens마다 PostGIS 검색을 실행하되 한 lens 전체에서 2~4곳만 round-robin으로
남긴다. 종류가 두 개인 purpose도 한 선반을 독점하지 않으며, lens끼리 점수 하나로 섞지 않는다.
이 경계 역시 외부 `/v2/places/search` 계약은 변경하지 않는다.

## 사용자 확인과 target 잠금

개발 lab의 검색 응답은 executable lens마다 짧게 유지되는 일회용 confirmation offer를 발급한다.
클라이언트가 다시 보낼 수 있는 것은 `lens_id`와 opaque token뿐이며 target, source, origin, locked를
직접 제출할 수 없다. 서버는 token이 가리키는 원본 `TargetSearchLens.confirmable_targets`만 새
`IntentObservation`으로 만들고 `source=user_confirmed`, `role=required_target`을 부여한 뒤 planner를
다시 통과시킨다.

확인 전후의 purpose 값은 같아야 한다. 달라지는 것은 provenance와 강도뿐이다.

```text
before: purpose.kind / inferred / unlocked / relaxable
explicit confirmation click
after:  purpose.kind / user_explicit / locked / not relaxable
```

원본 lens가 planner에 적용했던 공통 observation과 structured conditions는 다시 조립하지만,
`modifier_ids`나 unresolved facet을 확인된 사실로 승격하지 않는다. 실행 불가·선택 대기 lens는 target
확인만으로 우회할 수 없다. 탭 선택과 장소 마커 클릭은 계속 탐색 행동일 뿐이며 오직
`이 검색 방향을 명시적으로 확인` 버튼만 confirmation endpoint를 호출한다. offer는 만료·용량 제한·
single-use이며 이 상태 저장은 dev lab 프로세스 안에만 존재한다.

이 단계도 외부 `/v2/places/search` 계약이나 자동 완화, 신규 capability를 변경하지 않는다.

## 명시적 수정과 dev 관측

개발 lab은 자동 선택과 실제 사용자 행동을 구분한다. 첫 lens를 화면에 그리는 것은 이벤트가 아니고,
사용자가 다른 lens 탭을 누른 때만 `lens_selected`다. `처음부터 다시`를 누르면 `search_reset`이며,
페이지 이탈이나 무응답을 취소로 추정하지 않는다. 일반 `새 검색`은 화면에 이전 결과가 남아 있어도
독립 attempt다. 사용자가 발화를 고친 뒤 `현재 검색 수정`을 명시적으로 눌렀을 때만 새 attempt를
`previous_attempt_id`와 `search_revised`로 앞 시도에 연결한다.

blocking `cost.dimension` 중 현재 실행 가능한 선택은 `cost.travel_distance` 하나다. 사용자가
`가까운 곳`을 고르면 가격이 싸다고 주장하지 않고, 기본 거리 정렬을 비용의 proxy로 명시한 뒤 막혀
있던 target lens만 연다. 목적 target 없이 비용만 말한 경우에는 식사·나들이·문화의 넓은 제품
방향을 먼저 만들되 비용 축을 고르기 전에는 실행하지 않는다. 입장료·추가요금·상품 가격은 원천
coverage가 없으므로 계속 선택 불가다.
선택은 새 검색 attempt를 만들기 때문에 선택 전 0개 실행과 선택 후 실제 결과를 따로 비교할 수 있다.

`place_intent_lab_attempt`는 검색 상태·실패 코드·lens별 결과 수와 gate 잔여 수를 저장하고,
`place_intent_lab_event`는 선택·facet 수정·확인·초기화를 append-only로 저장한다. 실패는 적어도
provider 장애, 유효하지 않은 intent 출력, facet 선택 필요, 실행 lens 부재, 공간 후보 0건,
gate 전멸, 그 밖의 결과 0건, DB 검색 장애를
구분한다. `/dev/place-intent/observations`와 lab의 `Operator observations`가 최근 실패를 읽는다.

정량 평가에서 공급량과 UI 미리보기를 혼동하지 않도록 검색 수는 세 단계로 나눈다.
`initial_candidate_count`는 공간·목적 종류로 조회한 preview 후보, `eligible_candidate_count`는
마지막 gate 통과 후, `displayed_result_count`는 lens별 미리보기 제한까지 적용해 실제 반환한
개수다. preview 후보는 최대 1,000개로 제한되므로 잘린 종류가 하나라도 있으면
`initial_candidate_count_truncated=true`를 함께 기록해 이 값을 정확한 전체 수처럼 해석하지 않는다. 기존
`result_count`는 호환성을 위해 `displayed_result_count`와 같은 값으로만 기록한다. 과거 attempt의
초기·통과 후보 수는 복원할 수 없으므로 새 컬럼을 임의로 역산하지 않고 `NULL`로 보존한다.

이 저장은 `DAENGS_DEV_CONSOLE` 검증 표면만 호출한다. 재현을 위해 최대 1,000자의 발화 원문을
보존하므로 운영 검색에 그대로 연결해서는 안 된다. 운영 전에는 동의·보존 기간·삭제와 비식별화
정책을 별도로 결정해야 한다. 이 관측은 자동 완화를 실행하지 않으며, 이후 완화 정책의 근거만 만든다.
