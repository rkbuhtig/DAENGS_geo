---
status: proposed
implementation: none
---
# 행 태그 — `kind` 가 버린 차이를 되살린다

근거는 [태그 재료 측정](../../research/2026-08-27-tag-material.md) (2026-08-27),
결정은 [#70](../../decisions/2026-08-27-place-row-tags.md).
[pet-axes](pet-axes.md) 가 봉투를 축으로 만들었다면, 이 갈래는 그 축과 이름·원문을
**행 단위 탐색 어휘**로 투영한다.

## 문제 — 후보군 안이 평평하다

[결정 #65](../../decisions/2026-08-26-place-first-discovery.md)로 `kind` 후보군과 거리순은
섰다. 그런데 후보군 안에서 행끼리 구분이 안 된다.

| 같은 `kind` | 실제로는 |
|---|---|
| 슈가파인 애견카페 · 아트살롱 (`cafe`) | 개가 목적인 곳 / 내 커피에 개를 데려가는 곳 |
| 멍비치 강릉 · 삼척해수욕장 (`travel`) | 개 전용 해변(크기별 공간분리·유료) / 개 데려가는 해수욕장 |
| 성곡반려견놀이터 · ○○근린공원 (`travel`) | 뛰는 곳 / 걷는 곳 |

`travel` 1,632곳에서 반려견 놀이터 43곳이 공원 539곳에 묻힌다. 이 차이는 원천 category 가
버린 것이라 `kind` 정규화를 아무리 잘해도 복원되지 않는다.

## 재료는 어디에 있나

측정에서 확인된 것 (§6):

| kind | 가르는 재료 | 비고 |
|---|---|---|
| travel | restrictions 97% 유정보 + 이름 유형어 | 가장 강한 칼 |
| cafe | 동반 구역이 정확히 반반 (407/812) | 테라스만 vs 안까지 |
| pension | restrictions 41% (마리수·추가요금) | |
| pet_shop | 동반 불가 29% (1,570곳) | 개용품점인데 개는 밖 |
| hospital · pharmacy | 없음 | 쪼갤 이유도 없다 |

**재료가 여가 `kind` 에 몰려 있다.** 쏠림이 아픈 곳과 재료가 있는 곳이 같다.

## 갈래가 답해야 할 것

- [x] 첫 태그 사전 확정 — [결정 #72](../../decisions/2026-08-27-place-tag-catalog.md).
      이름 공간 `type:*` · `environment:*` · `activity:*` · `role:*`, 근거 등급은
      `name_rule` 하나. 어휘는 `app/place/tag_catalog.py` 에 버전과 함께 (PR B)
- [x] `restrictions` 291 문자열 매핑표 — `applies_to` 를 가진 구조로. 사람 전수 검토
      → `app/place/restriction_map.py`. 291/291 상태 배정, mapped 행 94%
- [ ] `travel` 유형어 목록 확정 (~19어). 토큰 채굴 결과가 씨앗 — #72 §3 에 후보,
      규칙표는 PR B 에서 골든 테스트와 함께 고정한다
- [x] 태그 커버리지 계수의 응답 형식 — `PlaceSearchGroup.restrictions`(그룹 옆, `sort` 밖).
      `sort.coverage` 는 정렬이 한 일을 말하는 자리라 정렬과 무관한 계수를 넣지 않았다.
      제한없음·조건있음·미상 + 원문 확인 필요 수를 센다
- [x] 배치 진입점 — `python -m app.ingest restrictions` (`pet_axes` 선례 그대로).
      리비전 `0018` 이 두 축(`restriction_state` × `parse_state`)과 술어 JSONB 를 만든다.
      33,611행 파생 확인 — 실측은 [측정 §5-1](../../research/2026-08-27-tag-material.md)
- [x] 파생 freshness — 저장된 `pet` 변경 시 축·술어를 함께 무효화하고 일반 배치가 다시
      고른다. resolver는 현재 semantics version이 아닌 술어를 `unknown`으로 내린다.
- [x] `applies_to` 투영 — `app/place/restriction_projection.py`. 소형견에게 대형견
      조건이 안 보이고, 증명 가능한 술어만 `incompatible` 로 올린다
- [ ] LLM 잔여 레인(언어유희 137곳)을 누가 도는가 — [#53](../../decisions/2026-08-24-agent-parallel-response.md)
      팀 경계와 묶인다

### 판정 경계 (PR 4 에서 확정)

술어는 넓게 적고 판정은 좁게 한다. `incompatible` 로 올리는 것은 **원문이 "못 들어온다"
고 말했고 프로필로 대조되는 것**뿐이다.

| 술어 | 판정 | 이유 |
|---|---|---|
| `deny:size@size:large` | ✅ | 원문이 크기로 배제했다 |
| `deny:age@age:*` | ✅ | `age_years` 로 대조. **문턱은 술어 `params` 가 갖는다** |
| `deny:species_dog` | ✅ | `고양이 전용`. 검색 주체가 개라 재료가 항상 있다 |
| `certainty=soft` 인 것 전부 | ❌ 표시만 | 원문이 단정하지 않았다 ("어려울 수 있음") |
| `require:muzzle` | ❌ 표시만 | 입마개를 채우면 간다 — 요구는 배제가 아니다 |
| `require:carrier`·`require:hold` | ❌ 표시만 | 시설이 말하는 케이지 규격을 모른다 |
| `deny:behavior`·`deny:health` | ❌ 표시만 | 이 개가 공격적인지·아픈지 모른다 |
| `deny:breed` | ❌ 표시만 | 열거된 견종 이름을 술어가 안 담는다 |

`owner.can_carry_kg` 가 살아나면 `require:hold` 는 그때 판정 대상이 된다 — 재료가
생기기 전에 추론으로 메우지 않는다.

## 이 갈래가 다루지 않는 것

- **공간 쏠림.** `shopping` 좌표 뭉침(김포아울렛 171행)은 venue 관계 문제다 (측정 §7).
- **의미 검색 레인.** #65 §5 의 보류 유지. 태그는 사용자가 적용하는 제안층까지다.
- **임베딩 자동 분류.** #70 §8 에서 기각했다. 발견 도구로만 남는다.
