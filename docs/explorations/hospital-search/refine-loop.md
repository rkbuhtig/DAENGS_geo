---
status: exploring
---
# 대화로 조건을 편집하는 루프

첫 검색은 **필터 없는 초안**. 마음에 안 들면 조건을 바꿔 재검색 — 사람이 원래 그렇게 함.

```
[초안] 좌표만 → search() → 화면
[대화] "너무 멀어" / "여기 말고" / "밤에 하는 데"
[LLM]  현재 상태 + 발화 → 툴 호출로 상태 변경
[검색] 바뀐 상태로 search()
[화면] 갱신 + changes 한 줄
```

LLM은 **검색을 하지 않는다. 조건을 편집한다.** 검색은 결정론적 함수 하나.

## 툴 (좁게)
`set_origin`, `set_radius` / `set_max_minutes`, `set_mode(walk|car|transit)`, `set_time(open_now|at|night|24h|emergency)`, `set_specialty`, `require(...)`, `exclude(ids)` / `pin(ids)`, `set_sort`, `undo`, `ask(q)`
- `min_rating` 없음 — 의도적. 데이터 없는 병원이 불리해지는 왜곡
- `exclude`의 "두 번째"는 사용자가 본 화면 기준 → 요청에 `shown_ids` 순서 포함

## 상태
`SearchParams` + `exclude_ids`, `pin_ids`, `sort`, `history`(undo). 처음엔 **무상태**(요청에 현재 params 포함) — 팀 세션 구조 확정 전엔 안전.

## 응답
`changes: string[]`는 **서버가 상태 diff로 생성.** LLM이 "좁혔어요"라 말했는데 안 바뀐 상황 방지.

## `ask()`가 실제로 쓰이는 지점
할매(안과·걸어서·낮) 케이스: 안과 특화는 멀리(2차 센터), 걸어서는 가까이 → 충돌. 검색이 못 풀고 "가까운 일반 병원 vs 멀지만 안과 있는 센터" 되물어야 함.
