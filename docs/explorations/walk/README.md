# 산책 — 탐색 갈래

**담당: 사용자.**

코어는 탐색이 아니라 계약이다 — [`contracts/walk-record.md`](../../contracts/walk-record.md), `app/features/walk/models.py`,
`tests/test_walk_contract.py`. 수집 → `WalkFacts`. 의미 없음.

`session-engine-draft`의 start/locations/finish 흐름은 아직 구현하지 않은 수집 코어의 실행 초안이다.
그 문서의 트리거·서술 절과 `loop-and-balance`는 산책 사실을 **소비하는 옵션**이며 현재 parked다.

| 갈래 | status | implementation | 한 줄 |
|---|---|---|---|
| [session-engine-draft](session-engine-draft.md) | exploring | draft | start/locations/finish 수집 흐름 초안. 트리거·서술 절은 parked |
| [session-continuity-and-dwell](session-continuity-and-dwell.md) | exploring | none | 세션과 GPS chain을 분리하고, 중단·재개·체류가 영역 칠하기에 주는 의미를 정리 |
| [territory-paint](territory-paint.md) | exploring | working-skeleton | 산책 점을 붓으로 지도를 칠한다. 산책 한 번 = 셀로판 한 장, 조건으로 골라 겹친다 |
| [drawn-region](drawn-region.md) | parked | working | 사용자가 면을 그리고 그 안의 체류를 잰다. 붓 모델로 대체 — 5배 규칙은 남는다 |
| [loop-and-balance](loop-and-balance.md) | parked | none | 3단 루프 · 케어 밸런스. 데이터 수집 전에는 결정하지 않음 |

`territory-paint` 는 `WalkFacts` 를 **소비하는** 갈래다. 수집 계약을 바꾸지 않으며, 셀 격자는
`app/geo/cells.py` 로 `anchors.py`·Android `LocalHexCellIndexer` 와 공유한다. 무엇을 영구히
남길지(단순화 궤적 vs 산책별 셀 맵)는 아직 열려 있고, 실사용 업로드는 #57·#58 이 막고 있어
지금 고를 필요가 없다.

`session-continuity-and-dwell`은 그 위에 제품 의미를 하나 더 분리한다. **한 산책 세션 안에 여러
GPS chain이 있을 수 있고, chain 사이의 관측 공백은 붓으로 연결하지 않는다.** 또한 반복 방문으로
겹쳐지는 색과 한 장소에서 오래 머무는 체류 표현을 같은 시각 축으로 굽히지 않는 안을 검토한다.

병원 찾기 쪽에서 나온 것 중 산책에도 쓰이는 것: 반경 검색(`app/geo/search.py`), 단발 경로 스냅샷(`app/journey`).
대화로 조건 편집하는 루프(`../hospital-search/refine-loop.md`)는 parked — 편집할 조건이 없었다.
