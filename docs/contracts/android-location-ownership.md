# Android 연속 위치 소유권 계약

한 시점에 연속 위치 구독자는 하나뿐이다. 지도 화면용 `LocationTracker`와 산책
`WalkTrackingService`가 동시에 고정밀 GPS를 받지 않도록 다음 세 입력만으로 소유자를 결정한다.

- 앱 화면: foreground / background
- 화면 feed: device / debug replay
- 산책: off / paused / recording

코드 계약은 `LocationOwnershipPolicy`, 전 조합 고정은 `LocationOwnershipPolicyTest`가 맡는다.

| 화면 | feed | 산책 | 연속 위치 소유자 |
|---|---|---|---|
| background | device/replay | off/paused | 없음 |
| background | device/replay | recording | 산책 foreground service |
| foreground | device | off/paused | 화면 device tracker |
| foreground | replay | off | 화면 replay tracker |
| foreground | replay | paused | 없음 — active walk와 replay를 섞지 않음 |
| foreground | device/replay | recording | 산책 foreground service |

별도 진입 규칙도 있다.

- replay는 산책이 `OFF`일 때만 시작한다.
- 산책은 화면 feed가 `DEVICE`일 때만 시작한다.
- background 진입은 실행 중 replay를 끝내고 device feed로 되돌린다.
- `PAUSED`는 산책 세션이 끝난 상태가 아니다. 화면이 보일 때 device tracker가 현재점 표시만 맡는다.

이 정책은 소유자만 판정한다. tracker 시작·중단, replay source 교체, UI 메시지는 현재
`MapViewModel`에 남아 있다. 다음 단계에서 이 부수효과를 별도 coordinator로 옮기더라도 이 표와
테스트는 바뀌지 않아야 한다.
