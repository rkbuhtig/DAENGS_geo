# Gemini 3.1 Flash-Lite Place intent calibration v3

## 결론

[첫 calibration](2026-09-02-place-intent-gemini-calibration.md)에서 드러난 mixed delegation과
role/semantic 오류를 같은 calibration 30건으로 수정했다. 첫 수정은 계약 유효율을 높였지만 안전
문장에서 검색을 과하게 여는 회귀를 만들었고, 이를 폐기한 뒤 두 번째 수정에서 안전 지표를 복구했다.

최종 prompt/schema의 결과는 다음과 같다.

- contract valid output `100%`
- search mode accuracy `96.7%`
- product outcome accuracy `100%`
- information delivery precision / recall `100% / 100%`
- inappropriate search `0%`
- unsafe positive target `0%`
- intent precision / recall `89.3% / 89.3%`
- 고정 probe 10건 × 3회의 세 stability 지표 `100%`

제품 진행과 안전 지표는 calibration에서 모두 통과했다. search mode 한 건과 같은 제품 결과를 만드는
purpose/kind 의미 차이 세 건은 known residual로 남긴다. 여기서 30문장에 더 맞추지 않고 이 계약을
holdout 후보로 동결하는 편이 과적합을 줄인다. holdout 20건은 이번 PR에서 열지 않는다.

## 변경한 경계

판정 순서를 다음처럼 명시했다.

```text
명시적 place kind / purpose / target형 semantic이 있는가?
  ├─ 예 → 추천·골라줘가 함께 있어도 directed_search
  └─ 아니오
       └─ 장소 선택 범위 자체를 맡긴 긍정적 근거가 있는가?
            ├─ 예 → open_discovery
            └─ 아니오 → directed_search 또는 abstained/ambiguous
```

세부 변경은 다음과 같다.

- `추천해줘`, `골라줘` 동사만으로 open discovery를 만들지 않는다.
- goal/preference/negated/excluded/hypothetical/relational만 있고 별도 위임 근거가 없으면 directed다.
- 두 개 이상의 명시적 장소 대안은 open으로 합치지 않고 directed interpretation을 나눈다.
- `-고 싶어`는 실제 goal, `-다면`과 `-나 갈까`는 hypothetical로 구분한다.
- 허용 semantic을 `quiet`, `cheap`, `dog_interest`로 schema에서도 닫아 `semantic.proximity` 발명을
  막는다.
- 정확한 kind에 더 넓은 purpose를 중복 생성하지 않는 예시와 outing/lodging canonical 예시를
  추가했다.
- Gemini 평면 schema의 search mode와 semantic 필드에도 같은 설명과 enum을 넣었다.

서버 계약은 완화하지 않았다. open discovery와 required target을 함께 낸 응답을 directed로 조용히
고치는 salvage도 추가하지 않았다.

## Baseline 대비 최종 결과

| metric | v1 baseline | v3 final | 변화 |
|---|---:|---:|---:|
| contract valid output | 83.3% | 100% | +16.7%p |
| invalid output | 16.7% | 0% | -16.7%p |
| disposition accuracy | 83.3% | 100% | +16.7%p |
| search mode accuracy | 76.7% | 96.7% | +20.0%p |
| open precision | 81.8% | 90.0% | +8.2%p |
| open recall | 100% | 100% | 동일 |
| open F1 | 90.0% | 94.7% | +4.7%p |
| explicit-target → open false positive | 6.7% | 0% | -6.7%p |
| product outcome accuracy | 80.0% | 100% | +20.0%p |
| information delivery precision | 100% | 100% | 동일 |
| information delivery recall | 84.0% | 100% | +16.0%p |
| inappropriate search | 0% | 0% | 동일 |
| intent precision | 54.2% | 89.3% | +35.1%p |
| intent recall | 46.4% | 89.3% | +42.9%p |
| unsafe positive target | 25.0% | 0% | -25.0%p |
| exact command recall | 83.3% | 83.3% | 동일 |
| unsupported intent visibility | 22.2% | 100% | +77.8%p |

분모가 없는 metric은 report에서 계속 `null`이며 표의 성공 수치에 섞지 않았다.

## 폐기한 첫 수정

첫 수정은 mixed delegation의 invalid output을 없앴지만 안전 문장에서 broad search를 열었다.

| metric | v2 first attempt |
|---|---:|
| contract valid output | 100% |
| search mode accuracy | 86.7% |
| product outcome accuracy | 93.3% |
| information delivery precision / recall | 92.6% / 100% |
| inappropriate search | 40.0% |

`병원 갈 정도는 아니야`를 open discovery로, `카페 말고 산책할 곳`을 exclusion을 실행하지 않는 broad
leisure 검색으로 바꾼 것이 핵심 회귀였다. aggregate 정확도 개선만 보고 이 prompt를 채택하면 안 된다.
해당 recording과 report를 남겨 다중 지표 gate가 실제로 막은 변경을 재현한다.

- [v2 rejected calibration recording](place-intent-gemini-calibration-v2/calibration-recording.json)
- [v2 rejected calibration report](place-intent-gemini-calibration-v2/calibration-report.json)

## Final calibration

| category | valid output | search mode | product outcome | inappropriate search |
|---|---:|---:|---:|---:|
| delegated open | 100% | 100% | 100% | N/A |
| explicit directed | 100% | 100% | 100% | N/A |
| mixed delegation | 100% | 100% | 100% | 0% |
| affective ambiguous | 100% | 100% | 100% | 0% |
| role safety | 100% | 83.3% | 100% | 0% |

이전 invalid 5건은 모두 계약 유효 출력이 됐다. 특히 `주차되는 식당 네가 골라줘`, `강아지랑 갈
숙소 알아서 골라줘`, `미술관 중에 네가 추천해줘`가 explicit target 안의 directed search로 유지됐다.
`강아지 장난감을 산다면`도 hypothetical로 보존됐으며 결과를 열지 않았다.

### Known residual

- `주차되면 좋겠어`는 parking preference를 보존했지만 search mode를 open discovery로 냈다. 제품은
  preference-only broad fallback을 실행하므로 product outcome은 정답과 같고 안전 회귀는 없었다.
- `산책할 곳`은 purpose `outing` 대신 kind `leisure`를 냈다.
- 두 lodging 문장은 purpose `lodging` 대신 kind `stay`를 냈다.

마지막 세 의미 차이는 현재 product lens가 같은 검색 방향을 만들지만 intent 정확도에는 그대로
오류로 계산했다. exact command recall `83.3%`도 `산책할 곳`의 canonical 차이를 숨기지 않는다.

## Stability

최종 prompt/schema로 calibration probe 10건을 세 번 호출했다.

| metric | 결과 |
|---|---:|
| contract valid output | 100% |
| search mode accuracy | 100% |
| product outcome accuracy | 100% |
| intent precision / recall | 100% / 100% |
| search mode stability | 100% |
| semantic output stability | 100% |
| product outcome stability | 100% |

세 run은 case별 의미 출력까지 동일했다. 다만 고정 probe에는 known residual인 parking preference-only와
outing/lodging 문장이 포함되지 않으므로, 이 안정성 수치가 그 세 문장의 일반화를 보장하지 않는다.

## 실험 계약과 artifacts

| 항목 | v2 rejected | v3 final |
|---|---|---|
| model | `gemini-3.1-flash-lite` | `gemini-3.1-flash-lite` |
| temperature | `0.0` | `0.0` |
| max output tokens | `1800` | `1800` |
| corpus SHA-256 | `1e627f...3542e` | `1e627f...3542e` |
| prompt SHA-256 | `019e9c...c2b1` | `7d372d...9805` |
| output schema SHA-256 | `ce0250...06c5` | `5f8b64...28db` |

최종 원출력과 report는 다음과 같다.

- [v3 calibration recording](place-intent-gemini-calibration-v3/calibration-recording.json)
- [v3 calibration report](place-intent-gemini-calibration-v3/calibration-report.json)
- [v3 stability recording](place-intent-gemini-calibration-v3/stability-recording.json)
- [v3 stability report](place-intent-gemini-calibration-v3/stability-report.json)

두 calibration은 같은 gold corpus를 사용했다. API key는 artifact에 저장하지 않았고 secret scan을
통과했다. 각 report는 recording에서 외부 호출 없이 다시 계산한 JSON과 일치한다.

## 다음 단계

이 prompt/schema를 더 이상 calibration에 맞추지 않고 동결한 뒤 holdout 20건을 한 번 평가한다.
holdout 결과가 known residual과 다른 실패군을 보이면 calibration 정답을 소급 수정하지 않고 별도
후속 계약으로 다룬다. 실제 DB candidate/eligible/displayed와 장소 품질 평가는 intent holdout 뒤의
별도 검색 평가 층이다.
