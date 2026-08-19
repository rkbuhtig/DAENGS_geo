---
status: adopted
date: 2026-08-19
decision: ../../decisions/README.md #25
---
# 정책 분리 — target(어디를 갈까) vs journey(어떻게 갈까)

두 조건은 **결과에 하는 짓이 다르다.** 코드에 안 박아두면 나중에 조용히 섞인다.

| | target | journey |
|---|---|---|
| 질문 | 어디를 갈까 | 어떻게 갈까 |
| 결과에 하는 일 | **필터** — 안 맞으면 결과 집합에서 사라짐 | **판정** — 결과를 빼지 않음. 경로 계산 방식과 advice만 바꿈 |
| 소비처 | `geo.search.find_places` | `geo.transport.snapshot_for` |
| 내용 | 반경 · 영업중/야간/응급 · 특화 · 필수태그 · 제외/고정 · 기준시각 | 이동수단 · 도보 옵션 · 피할 시설 · 시간 상한 |

`view`(정렬·undo·reset)는 어느 쪽도 아니다. 표시 정책.

## 코드 구조
```
SearchState
├── lat, lng                 공통 기준점
├── target: TargetPrefs      radius_m, open_now, night, emergency, at, specialty, require_tags, exclude_ids, pin_ids, limit
├── journey: JourneyPrefs    mode, walk{option, avoid}, max_min, hard_limit
├── sort                     view
└── history                  undo 스택

tools.py   TARGET_TOOLS / JOURNEY_TOOLS / VIEW_TOOLS  (+ policy_of())
diff.py    changes_by_policy() → {target[], journey[], view[]}
nl.py      TOOL_SPECS에 policy 포함 → LLM도 두 정책을 구분해서 고른다
api        find_places(tg.*) / snapshot_for(jn.*) — 서로의 값을 넘기지 않는다
```

## 경계를 넘는 유일한 지점: `journey.hard_limit`
"15분 안"은 두 가지로 읽힌다 — "15분 넘으면 표시해줘" vs "빼줘". 기본은 **표시만**(`advice=avoid`),
사용자가 명시적으로 켤 때만 결과에서 제외하고 응답에 `(N곳은 시간 초과로 제외)`를 남긴다.

## 테스트로 지킨다 (tests/test_refine.py)
- 모든 툴이 정확히 한 정책에 속함 (누락·중복 없음)
- `TOOL_SPECS`가 모든 툴을 덮고 policy가 일치함 — 이 테스트가 `set_origin`·`unrequire`가 LLM 툴 목록에서 빠져 있던 걸 잡았다
- JOURNEY_TOOLS는 `target`을 건드리지 않음 / TARGET_TOOLS는 `journey`를 건드리지 않음
- `max_min`은 hard 없이는 필터가 아님

## 실측 (policy_check)
```
② journey 3연발(도보/계단제외/지하도 피함) → 결과 집합 동일, 순서만 바뀜
③ target '야간에 하는 데'                  → 6곳 → 3곳
⑤ 15분 상한 (표시만)                       → 6곳 유지, 5곳 advice=avoid
⑥ 15분 상한 (hard)                        → 1곳, "5곳은 시간 초과로 제외"
```

## 알려진 느슨한 곳
`set_mode`(journey)가 `sort`(view)를 duration으로 바꾼다 — 편의. view는 결과 집합을 안 바꾸니 정책 위반은 아니지만 유일한 교차점.
