# Gemini 3.1 Flash-Lite Place intent holdout

## 결론

[v3 calibration](2026-09-02-place-intent-gemini-calibration-v3.md)에서 동결한 prompt/schema를
수정하지 않고, 처음 열어 본 holdout 20건을 한 번 실호출했다. 결과는 다음과 같다.

- contract valid output `95%`
- search mode accuracy `85%`
- product outcome accuracy `90%`
- information delivery precision / recall `93.8% / 100%`
- inappropriate search `20%`
- intent precision / recall `72.2% / 68.4%`
- explicit-target → open false positive `0%`
- unsafe positive target `0%`

명시적 target을 open discovery로 뒤집지 않았고, 정보를 줘야 하는 15건은 모두 결과 제공 경로를
유지했다. 반면 검색하면 안 되는 5건 중 1건을 실행해 inappropriate search가 `20%`가 됐다. 또한
1건은 구조화 출력 검증에 실패했다. 따라서 이 결과만으로 현재 계약을 제품 승격 준비 완료라고
판정할 수 없다. 특히 제외 조건의 role 보존과 구조화 출력 유효성은 별도 후속 계약이 필요하다.

이번 PR에서는 holdout을 본 뒤 prompt/schema, corpus gold, evaluator를 수정하지 않는다. 이 20건은
이제 소비된 평가 자료이며 후속 수정의 회귀 집합으로만 사용한다. 후속 계약을 보정한 뒤 일반화를
다시 주장하려면 이 문장들과 겹치지 않는 새 holdout이 필요하다.

## 실험 절차

- model: `gemini-3.1-flash-lite`
- temperature: `0.0`
- max output tokens: `1800`
- 모집단: `open_discovery_cases.json`의 고정 holdout 20건
- 반복: case별 1회
- prompt SHA-256: `7d372d...9805`
- output schema SHA-256: `5f8b64...28db`
- holdout corpus SHA-256: `2c6d11...121e`

첫 실행은 14건을 완료한 뒤 provider `429 Too Many Requests`로 중단됐다. 즉시 재개도 같은 시간창의
429를 받았고, 호출 창이 지난 뒤 같은 recording에서 남은 6건만 재개해 완료했다. provider 오류는
모델 오답으로 세지 않았으며 완료된 case를 다시 호출하지 않았다. recording의 digest 검증으로
재개 전후 prompt/schema/model/corpus가 같음을 확인했다.

API key는 artifact에 저장하지 않았다. recording과 report는 다음과 같다.

- [holdout recording](place-intent-gemini-holdout/holdout-recording.json)
- [holdout report](place-intent-gemini-holdout/holdout-report.json)

## Calibration 대비 holdout

| metric | v3 calibration | holdout | 변화 |
|---|---:|---:|---:|
| contract valid output | 100% | 95% | -5.0%p |
| invalid output | 0% | 5% | +5.0%p |
| disposition accuracy | 100% | 90% | -10.0%p |
| search mode accuracy | 96.7% | 85% | -11.7%p |
| open precision | 90% | 77.8% | -12.2%p |
| open recall | 100% | 87.5% | -12.5%p |
| open F1 | 94.7% | 82.4% | -12.3%p |
| explicit-target → open false positive | 0% | 0% | 동일 |
| product outcome accuracy | 100% | 90% | -10.0%p |
| information delivery precision | 100% | 93.8% | -6.2%p |
| information delivery recall | 100% | 100% | 동일 |
| inappropriate search | 0% | 20% | +20.0%p |
| intent precision | 89.3% | 72.2% | -17.1%p |
| intent recall | 89.3% | 68.4% | -20.9%p |
| unsafe positive target | 0% | 0% | 동일 |
| exact command recall | 83.3% | 75% | -8.3%p |
| unsupported intent visibility | 100% | 75% | -25.0%p |

holdout은 repeat 1이므로 세 stability 지표는 비교 대상이 없어 `null`이다. calibration의 10건 × 3회
안정성 `100%`와 직접 비교하지 않는다.

## 사례별 판정

### 실제 제품 행동 실패

| case | 입력 | 기대 | 실제 | 영향 |
|---|---|---|---|---|
| `mixed-10` | `카페 말고 네가 추천해줘` | `safe_no_search` | `invalid_output` | `kind` 값을 누락한 구조화 출력이라 제외 조건과 open 위임을 실행하지 못함 |
| `safety-09` | `병원 말고 약국 찾아줘` | `safe_no_search` | `results_now` | `병원`을 `excluded`가 아닌 `negated`로 분류해 현재 lens가 제외 조건을 보존하지 못하고 검색을 실행함 |

`safety-09`는 required target인 약국 자체는 맞췄고 unsafe positive target도 만들지 않았다. 하지만
제품 계약상 실행 전에 보존해야 할 제외 조건을 다른 role로 바꿨으므로 정보 제공 recall과 별개로
안전 실패다. holdout의 inappropriate search `20%`는 검색 금지 기대 5건 중 이 1건에서 발생했다.

### 검색 모드·해석 오류지만 같은 제품 진행 결과

| case | 기대 | 실제 | 제품 결과 |
|---|---|---|---|
| `affect-02` `싸게 갈 수 있는 곳` | preference-only directed | open discovery + cheap preference | 둘 다 `results_with_refinement` |
| `affect-08` `강아지가 좋아하는 거 있는 곳` | preference-only directed | open discovery + dog-interest preference | 둘 다 `results_now` |
| `affect-06` `강아지랑 잠깐 머물 곳` | dining/outing의 ambiguous 해석 | `stay` 하나로 proposed | 둘 다 `results_now` |

앞의 두 건은 별도 위임 근거 없이 preference 문장 자체를 open 근거로 사용했다. 이는 calibration의
`주차되면 좋겠어` known residual과 같은 경계가 다른 semantic에도 일반화된 것이다. 다만 현재
preference-only broad fallback 때문에 결과 제공 행동은 gold와 같았다.

`affect-06`은 gold가 보존한 두 해석 대신 `머물 곳`을 숙박 kind로 읽었다. 자연어상 가능한 해석이지만
동결한 gold와는 다르므로 disposition과 intent 오류로 그대로 계산한다. 이번 결과를 보고 gold를
소급 수정하지 않는다.

### 반복된 ontology 차이와 과잉 의미

- `강아지랑 갈 숙소 찾아줘`: purpose `lodging` 대신 kind `stay`
- `숙소 근처 카페 찾아줘`: relational purpose `lodging` 대신 relational kind `stay`
- `미술관 보고 싶어`: 정확한 kind `gallery`에 goal purpose `culture`를 추가

lodging/stay 차이는 calibration에서도 보였던 known residual이 holdout에서도 반복된 것이다. 실행할
장소군은 같지만 exact intent 비교에서는 오류다. 이는 prompt 품질 조정과 별개로 purpose/kind
canonicalization 책임을 어디에 둘지 결정해야 함을 보여준다.

## 범주별 관찰

| category | valid output | search mode | product outcome | inappropriate search |
|---|---:|---:|---:|---:|
| delegated open | 100% | 100% | 100% | N/A |
| explicit directed | 100% | 100% | 100% | N/A |
| mixed delegation | 75% | 75% | 75% | 0% |
| affective ambiguous | 100% | 50% | 100% | 0% |
| role safety | 100% | 100% | 75% | 33.3% |

open 위임과 명시적 장소 target의 큰 경계는 holdout에서도 보존됐다. 약점은 세부적으로 mixed
exclusion의 구조화 출력, preference-only 문장의 open 과잉 선언, `excluded`와 `negated`의 role
구분에 모였다. aggregate prompt를 다시 넓히기보다 이 세 실패 비용을 분리해 다루는 편이 맞다.

## 다음 단계

1. 이번 holdout PR에서는 계약을 동결하고 recording/report만 확정한다.
2. 후속 PR에서 `excluded`/`negated`가 검색 실행 가능성에 미치는 차이를 서버 계약과 lens까지 함께
   명시하고, invalid flat payload의 필수 필드 누락을 별도 회귀로 고정한다.
3. lodging/stay 및 dining/outing 차이는 prompt 예시를 더 넣기 전에 ontology canonicalization 문제로
   분리해 결정한다.
4. 수정 후 소비된 20건은 회귀 집합으로 돌리되, 새 문장군으로 별도 holdout을 만든다.
5. intent 계약이 다시 안전해진 뒤 실제 DB의 candidate/eligible/displayed와 장소 품질 평가로 넘어간다.
