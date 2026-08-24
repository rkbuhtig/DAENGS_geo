# 산책 — 탐색 갈래

**담당: 사용자.**

코어는 탐색이 아니라 계약이다 — [`contracts/walk-record.md`](../../contracts/walk-record.md), `app/features/walk/models.py`,
`tests/test_walk_contract.py`. 수집 → `WalkFacts`. 의미 없음.

`session-engine-draft`의 start/locations/finish 흐름은 아직 구현하지 않은 수집 코어의 실행 초안이다.
그 문서의 트리거·서술 절과 `loop-and-balance`는 산책 사실을 **소비하는 옵션**이며 현재 parked다.

| 갈래 | status | implementation | 한 줄 |
|---|---|---|---|
| [session-engine-draft](session-engine-draft.md) | exploring | draft | start/locations/finish 수집 흐름 초안. 트리거·서술 절은 parked |
| [loop-and-balance](loop-and-balance.md) | parked | none | 3단 루프 · 케어 밸런스. 데이터 수집 전에는 결정하지 않음 |

병원 찾기 쪽에서 나온 것 중 산책에도 쓰이는 것: 반경 검색(`app/geo/search.py`), 단발 경로 스냅샷(`app/journey`).
대화로 조건 편집하는 루프(`../hospital-search/refine-loop.md`)는 parked — 편집할 조건이 없었다.
