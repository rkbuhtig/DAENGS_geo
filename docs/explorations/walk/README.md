# 산책 — 탐색 갈래

**담당: 사용자.**

코어는 탐색이 아니라 계약이다 — [`contracts/walk-record.md`](../../contracts/walk-record.md), `app/features/walk/models.py`,
`tests/test_walk_contract.py`. 수집 → `WalkFacts`. 의미 없음.

아래는 전부 그 사실을 **소비하는 옵션**이다. 순서 없고, 각자 결정이고, 바깥 팀원이 맡을 수도 있다.

| 갈래 | status | 한 줄 |
|---|---|---|
| [session-engine-draft](session-engine-draft.md) | exploring | 세션 API 흐름 초안 (08-19). 트리거·서술 절은 코어 아님 |
| [loop-and-balance](loop-and-balance.md) | exploring | 3단 루프 · 케어 밸런스. `overview.md` 에서 내림 (08-22) |

병원 찾기 쪽에서 나온 것 중 산책에도 쓰이는 것: 반경 검색(`app/geo/search.py`), 단발 경로 스냅샷(`app/journey`).
대화로 조건 편집하는 루프(`../hospital-search/refine-loop.md`)는 보류 — 편집할 조건이 없었다.
