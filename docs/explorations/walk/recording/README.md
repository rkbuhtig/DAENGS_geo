# 산책 기록·관측·재생

[산책 전체 입구](../README.md) · [공간 분석](../spatial/README.md)

| 작업 | 기준 문서 |
|---|---|
| 세션 연속성·복구·관측 공백 | [연속성과 체류](session-continuity-and-dwell.md) |
| 산책·센서 입력 생성과 실행 명령 | [시뮬레이터 코어](simulator-core.md) |
| 같은 관측의 Android·GPX·ADB 재생 | [Android 재생 어댑터](android-replay-adapter.md) |
| 실기기 export의 공간 계산 재생 | [Cellophane 실기기 재생](cellophane-device-replay.md) |
| 보류한 속도별 동선 표현 | [속도색 동선](speed-colored-trail.md) |
| 초기 세션 흐름의 배경 | [세션 엔진 초안](session-engine-draft.md) |

공용 계산은 [app/features/walk](../../../../app/features/walk/), 재사용 생성기는
[scripts/sim/walk](../../../../scripts/sim/walk/)에 있다. 실행·입력·출력 조건은 위 재생·시뮬레이터 문서를 따른다.

사실과 소비자 경계는 [수집 계약](../../../contracts/walk-record.md),
[CanonicalTrail 계약](../../../contracts/canonical-trail-consumers.md),
[결정 #84](../../../decisions/2026-09-03-canonical-trail-consumer-boundary.md)를 읽는다.
실험 결과는 [산책 기록 lab 기록](../../../research/2026-09-05-walk-record-lab.md)으로 연결한다.
운영 채택은 [승격 원장](../../../promotion-ledger.toml)과 [Android 실행 안내](../../../../android/README.md)에서 확인한다.
