# 산책 — 탐색 갈래

**담당: 사용자.**

## 주제별 입구

| 찾는 작업 | 입구 |
|---|---|
| 기록·연속성·관측·재생 | [recording](recording/README.md) |
| 붓·셀로판·국소 조회·공간 분포 | [spatial](spatial/README.md) |
| 일기·장면·행동 증언·기억 | [diary](diary/README.md) |
| 점령·인증·시즌·제작·이관 | [game](game/README.md) |
| 산책·점령 세션의 통계 연결 | [statistics](statistics/README.md) |

새 탐색은 해당 하위 폴더에 두고 그 README에서 연결한다. 확정 계약·결정·날짜별 실험 결과는
기존 `contracts/`·`decisions/`·`research/`가 소유한다. 폴더 분류는 채택 상태를 바꾸지 않는다.
DEV·APP 채택 기준은 [승격 원장](../../promotion-ledger.toml)과 각 주제의 계약·인수인계를 따른다.

## 공통 경계

수집 코어는 [산책 사실 계약](../../contracts/walk-record.md)을 따른다.
[app/features/walk](../../../app/features/walk/)가 수집·사실·Capsule을 생산하며,
[tests/walk](../../../tests/walk/)가 이를 검증한다. 산책이 봉인된 뒤의 공간 조회·일기·게임은
각자의 정책과 수명으로 증거를 읽는다. 해석이나 사용자 증언을 `WalkFacts`로 되밀지 않는다.
공통 입력의 범위는 [CanonicalTrail 계약](../../contracts/canonical-trail-consumers.md)을 따른다.

공간 분석은 산책별 Cellophane을 보존하고 조건별로 골라 읽는다. 방문률·시간·체류와
공간 이용 분포는 분모와 연산이 다르며, 상세 계획과 계약은 [공간 입구](spatial/README.md)에 있다.
장면·일기는 [독립 장면과 별도 일기 생성 기획](diary/plan.md)과 [자료 카탈로그](diary/evidence-catalog.md),
게임은 [구현·이관 인수인계](game/territory-game-handoff.md)에서 작업을 재개한다.

## 탐색과 구현을 읽는 법

각 하위 README가 갈래와 기준 문서를 연결한다. `status`·`implementation`과 남은 과제는
해당 문서에서 확인하며 이 입구에 전체 상태표를 중복 관리하지 않는다.

- [초기 세션 엔진](recording/session-engine-draft.md)은 설계 배경이다. 현재 수집 구현은
  [Android 기준 구현](../../../android/README.md)과 산책 계약을 함께 읽는다.
- [시즌 점수](game/territory-season-scoring.md)는 이전 정기 정산 가설이다.
  현재 로컬 규칙·검증은 [시즌 게임](game/territory-season-game.md)에서 확인한다.
- [기억 엔진](diary/memory-engine.md)은 탐색의 배경과 열린 가설을 남긴다.
  채택된 좁은 범위는 [결정 #74](../../decisions/2026-09-01-spatial-diary.md)와 후속 계약을 따른다.

공유 Place 검색은 [Place v2 계약](../../contracts/place-search-v2.md), 이동 snapshot은
[Journey](../hospital-search/journey-view.md)에서 찾는다.
