# Android 연속 위치 소유권 계약

한 시점에 연속 위치 구독자는 하나뿐이다. 지도 화면용 `LocationTracker`와 산책
`WalkTrackingService`가 동시에 고정밀 GPS를 받지 않도록 다음 세 입력만으로 소유자를 결정한다.

- 앱 화면: foreground / background
- 화면 feed: device / debug replay
- 산책: off / paused / recording

코드 계약은 `LocationOwnershipPolicy`, 전 조합 고정은 `LocationOwnershipPolicyTest`가 맡는다.
정책에 따라 화면 tracker를 실제로 시작·중단하는 단일 주체는 `LocationFeedCoordinator`다.

| 화면 | feed | 산책 | 연속 위치 소유자 |
|---|---|---|---|
| background | device/replay | off/paused | 없음 |
| background | device/replay | recording | 산책 foreground service |
| foreground | device | off/paused | 화면 device tracker |
| foreground | replay | off | 화면 replay tracker |
| foreground | replay | paused | 없음 — active walk와 replay를 섞지 않음 |
| foreground | device/replay | recording | 산책 foreground service |

표의 조합 중 넷(`background × replay` 둘, `foreground × replay × paused/recording`)은 아래 진입
규칙 때문에 **현재 도달할 수 없다.** 그래도 정책과 테스트가 값을 고정한다 — 진입 규칙을 푸는
변경이 있을 때 동작이 슬쩍 바뀌는 대신 이 표가 먼저 깨지게 하려는 것이다.

별도 진입 규칙도 있다.

- replay는 산책이 `OFF`일 때만 시작한다.
- 산책은 화면 feed가 `DEVICE`일 때만 시작한다.
- background 진입은 실행 중 replay를 끝내고 device feed로 되돌린다.
- `PAUSED`는 산책 세션이 끝난 상태가 아니다. 화면이 보일 때 device tracker가 현재점 표시만 맡는다.

산책 상태의 출처는 `WalkTrackingController` 하나다. `uiState.trail` 은 collector 가 채우는 화면
미러라서, `start()` 와 다음 emission 사이에는 아직 `OFF` 로 읽힌다 — 그 창에서 소유권을 판정하면
두 번째 구독이 열린다.

이 정책은 소유자만 판정한다. tracker 시작·중단, replay source 교체, 앱 visibility와 산책 상태에
따른 전환은 `LocationFeedCoordinator`가 맡는다. `MapViewModel`에는 검색 명령과 화면 상태 투영만
남으며, `WalkTrackingService`는 기록 중인 실제 GPS 구독을 계속 독립 소유한다.
