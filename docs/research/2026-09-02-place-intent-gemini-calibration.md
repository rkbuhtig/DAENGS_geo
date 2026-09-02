# Gemini 3.1 Flash-Lite Place intent calibration

## 결론

현재 prompt와 schema를 holdout에 고정하기에는 이르다. 정보 우선 제품 진행은 비교적 보수적으로
동작했지만, Gemini가 명시적 목적 안에서 골라 달라는 표현까지 `open_discovery`로 넓히는 경향과
role·intent 계약 위반이 calibration에서 확인됐다.

- calibration 30건의 계약 유효 출력은 `25/30 (83.3%)`다.
- search mode 정확도는 `23/30 (76.7%)`, product outcome 정확도는 `24/30 (80.0%)`다.
- 결과를 내면 안 되는 문장에서 검색한 비율은 `0/5 (0%)`다.
- 결과를 먼저 줘야 하는 문장의 정보 제공 recall은 `21/25 (84.0%)`다.
- 고정 probe 10건은 3회 모두 같은 출력을 냈다. 세 stability 지표는 모두 `100%`다.
- 하지만 `조용한 곳`을 세 번 모두 `open_discovery`로 분류했다. 안정성은 정확성의 대체 지표가
  아니다.

따라서 이번 결과는 모델 채택 판정이나 holdout 점수가 아니다. 다음 calibration PR에서
`open_discovery` 경계와 role 출력을 조정한 뒤 같은 calibration을 다시 측정한다. 그 변경을 동결하기
전에는 holdout 20건을 열지 않는다.

## 실험 계약

| 항목 | 값 |
|---|---|
| provider / model | Gemini / `gemini-3.1-flash-lite` |
| corpus | calibration 30건, 5개 범주 |
| stability | calibration probe 10건 × 3회 |
| temperature | `0.0` |
| max output tokens | `1800` |
| corpus SHA-256 | `1e627fb580b98945b6e2f3c75a1f512f523292ff7bfe806b2c70715d7ca3542e` |
| prompt SHA-256 | `911240960f2db5ea027fda683b6398f386ec249a29c6aba03bd4e65cd404c513` |
| output schema SHA-256 | `05eb7fa14448711359bd03947c11e90fab0d75c927e0acabd8f13c017ab49883` |

원출력과 수식 결과는 다음 파일에 분리했다.

- [calibration recording](place-intent-gemini-calibration/calibration-recording.json)
- [calibration report](place-intent-gemini-calibration/calibration-report.json)
- [stability recording](place-intent-gemini-calibration/stability-recording.json)
- [stability report](place-intent-gemini-calibration/stability-report.json)

API key는 어느 artifact에도 저장하지 않았다. invalid output의 raw 응답은 고정된 합성 평가 문장의
계약 실패를 재현하기 위해서만 recording에 남겼다.

## Calibration 결과

| metric | 결과 |
|---|---:|
| contract valid output | 83.3% |
| invalid output | 16.7% |
| disposition accuracy | 83.3% |
| search mode accuracy | 76.7% |
| open discovery precision / recall / F1 | 81.8% / 100% / 90.0% |
| explicit-target → open false positive | 6.7% |
| grounded output | 83.3% |
| valid open-discovery grounding | 100% |
| product outcome accuracy | 80.0% |
| information delivery precision / recall | 100% / 84.0% |
| inappropriate search | 0% |
| intent precision / recall | 54.2% / 46.4% |
| unsafe positive target | 25.0% |
| exact command recall | 83.3% |
| unsupported intent visibility | 22.2% |

단일 calibration run의 stability 값은 비교 대상이 없으므로 `null`이다. stability는 아래의 별도 3회
반복만 해석한다.

### 범주별 병목

| category | valid output | search mode | product outcome |
|---|---:|---:|---:|
| delegated open | 100% | 100% | 100% |
| explicit directed | 100% | 100% | 83.3% |
| mixed delegation | 50.0% | 50.0% | 50.0% |
| affective ambiguous | 83.3% | 66.7% | 83.3% |
| role safety | 83.3% | 66.7% | 83.3% |

`mixed_delegation`이 가장 먼저 고쳐야 할 범주다. 사용자가 목적을 말한 뒤 “골라줘”라고 하면
Gemini가 목적 안에서의 선택을 시스템 전체에 대한 위임으로 넓히는 경향이 있었다.

## Invalid output 5건

다음 응답은 provider 호출에는 성공했지만 서버의 authority-free intent 계약을 통과하지 못했다.

| case | 발화 요약 | raw 출력의 충돌 |
|---|---|---|
| `mixed-02` | 주차되는 식당을 골라 달라 | open discovery + restaurant required target + parking required condition |
| `mixed-04` | 강아지와 갈 숙소를 골라 달라 | open discovery + lodging required target |
| `mixed-05` | 미술관 중 추천 | open discovery + gallery required target |
| `affect-09` | 카페와 산책 중 고민 | 두 대안 모두 open discovery이며 각각 explicit target/goal 포함 |
| `safety-05` | 장난감을 산다면 | open discovery + hypothetical activity/object |

앞의 세 건은 “무엇을 찾을지 위임”과 “명시된 목적 안에서 하나를 골라 달라”를 혼동한 같은 계열이다.
`affect-09`는 대안 해석과 open directive를 섞었고, `safety-05`는 가정 문장을 탐색 위임으로 올렸다.
서버가 이 응답을 실행하지 않은 것은 올바르지만, 이전 evaluator는 첫 invalid에서 전체 측정을
중단했다. 이번 PR은 invalid를 완료된 품질 결과로 기록하고 나머지 case를 계속 평가한다.

## 유효 출력에서 확인된 오류

- `direct-03`은 가까운 병원 요청에 `semantic.proximity`를 필수조건으로 추가했다. 현재 planner가
  이 semantic을 실행할 수 없어 product outcome이 `results_now`가 아니라 `safe_no_search`가 됐다.
- `affect-01`의 `조용한 곳`과 `safety-06`의 주차 preference-only 문장을
  `open_discovery`로 과잉 선언했다. 제품은 넓은 결과를 제공했지만 search mode 정답은 아니다.
- `safety-03`의 “카페나 갈까”를 hypothetical이 아니라 required target으로 올렸다. calibration의
  unsafe positive target `25%`를 만든 사례다.
- `direct-06`, `mixed-01`, `mixed-03`, `mixed-06`, `safety-02`, `safety-04`에서도 purpose/kind 또는
  goal/preference/hypothetical role 차이가 있었다. product 결과가 같더라도 의미 계약 정확도에는
  포함한다.

근거 quote는 유효 출력에서 모두 원문에 고정됐다. 현재 병목은 evidence hallucination보다
search-mode와 role/intent 선택이다.

## Stability 결과

고정 probe 10건을 같은 계약으로 세 번 호출했다.

| metric | 결과 |
|---|---:|
| contract valid output | 100% |
| search mode stability | 100% |
| semantic output stability | 100% |
| product outcome stability | 100% |
| mean search mode accuracy | 90.0% |
| mean product outcome accuracy | 100% |

세 run은 case별 출력까지 동일했다. 다만 affective probe의 `조용한 곳`도 매번 같은
`open_discovery + semantic.quiet preference`로 나왔다. 이는 temperature 0에서 재현 가능한
체계적 경계 오류이며, 단순 재호출로 해결할 문제가 아니다.

## 실행 중 관측된 evaluator 동작

두 실측 모두 30번째 부근에서 Gemini `429`를 만났고 recording은 각각 `29/30`까지 보존됐다.
HTTP 오류는 완료 결과로 만들지 않았으므로 `--resume`은 마지막 한 건만 다시 호출했다. 반대로
intent 계약 위반은 `invalid_output`으로 기록하고 다음 case로 진행했다. 이 구분으로 품질 실패와
일시 provider 장애를 섞지 않고 실제 재개 경로도 검증했다.

## 다음 calibration 변경의 우선순위

1. 명시적 target 안에서 “골라줘/추천해줘”라고 한 문장은 directed search라는 경계를 prompt와
   Gemini 평면 schema 예시에 더 강하게 고정한다.
2. 가정·망설임·preference-only 문장을 open discovery로 올리지 않고 role을 보존한다.
3. `semantic.proximity`처럼 현재 planner가 실행하지 못하는 추가 필수조건을 모델이 발명하지 않게
   canonical semantic 범위를 닫는다.
4. 같은 30건과 10×3 probe를 다시 측정해 invalid output, search mode, product outcome을 비교한다.
5. 기준을 동결한 뒤에만 holdout 20건을 한 번 평가한다.

이번 단계는 planning pipeline의 실행 가능 여부까지 평가한다. 홍대 등 실제 DB에서의 후보 수,
eligible/displayed funnel과 장소 품질 평가는 이 intent calibration과 분리된 다음 평가 층이다.
