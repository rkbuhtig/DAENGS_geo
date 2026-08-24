# DAENGS Android 워킹 스켈레톤

기존 스냅샷 검증: 2026-08-24 — 단위 테스트 32개와 `assembleDebug` 통과. 이 변경은 산책
foreground service를 추가하며, 실기기 화면 OFF/다른 앱 전환 smoke는 별도 확인이 필요하다.

`android/app` 단일 모듈이 실제 위치에서 `POST /hospital/search`를 호출하고 NAVER 지도,
마커, 하단 병원 카드, `actions[]`, 안전 통지, 전화 동작을 렌더링한다. 같은 지도에서 현재 위치,
서비스 소유 산책 트레일과 로컬 territory 레이어도 실행한다.

## 경계

```text
location/  단발·연속 위치 계약, Fused 제공자, 가상 경로 재생, 연속 구독 primitive
hospital/  HTTP 계약. state와 actions[].edits는 JsonObject/JsonArray로 불투명 왕복
walk/      foreground service + 기록 상태/controller/store + TrailRecorder. 산책 중 GPS 소유자
map/shell  단일 MapHost와 제공사 독립 MapScene
map/layers 장소·트레일·territory의 구체적인 렌더 상태
map/provider/naver  MapScene을 NAVER SDK 오버레이로 변환
territory/ 서버 없는 개인 마킹 저장소와 순수 Kotlin 로컬 육각 격자
app        DaengsApplication 조립점. DI 프레임워크 없음
```

앱이 소유하는 위치는 두 개다.

- `deviceLocation`: 실제 기기 fix만 쓴다. `follow_device` 검색 origin의 진실이다.
- `searchOrigin`: 서버 state에 들어 있는 현재 검색 기준점이다.

`follow_device` 검색은 요청 시점의 최신 위치를 top-level `origin`에 붙인다. 지도 이동 후
`pinned` 검색은 `set_origin` edit만 보내고 top-level `origin`을 생략한다. 이 규칙은
`SearchRequestBuilderTest`가 고정한다.

### 화면 위치와 산책 기록의 소유권

산책하지 않을 때 연속 위치는 `MapViewModel`의 screen-owned `LocationTracker`가 맡는다. 이 구독은
Activity가 화면을 벗어나면 중단한다. `동선 기록 시작`을 누르면 screen-owned 구독을 먼저 멈추고
`WalkTrackingService`가 location foreground service로 승격한 뒤 자기 `LocationTracker`와
`TrailRecorder`를 소유한다. 따라서 Activity의 `onStop()`은 화면용 구독만 끊고 진행 중 산책을
중단하지 않는다.

일시정지 중에는 서비스가 GPS 구독을 멈춘다. 앱 화면이 보이면 화면용 구독을 다시 써 현재점을
보여주고, `계속 기록` 시 다시 서비스가 고정밀 연속 구독을 가져간다. 종료하면 서비스가
foreground 상태를 내리고 화면용 구독이 다시 주인이 된다. UI는 `WalkTrackingStore`의 상태를
관찰할 뿐 산책 세션이나 `TrailRecorder`를 소유하지 않는다.

서비스는 `foregroundServiceType="location"`과 `FOREGROUND_SERVICE_LOCATION`을 선언한다.
산책 시작은 사용자가 보이는 Activity에서 직접 누르는 동작으로만 시작한다. 그래서 이 단계에서는
`ACCESS_BACKGROUND_LOCATION`을 요청하지 않는다. 지속 알림에는 일시정지/계속 기록/종료 액션이
있다.

현재 store는 **프로세스 메모리**다. `START_NOT_STICKY`라 프로세스가 죽은 뒤 근거 없이 산책을
자동 복원하지 않는다. Room/SQLite 저장과 서버 세션 업로드가 붙기 전까지는 process-death 복구를
보장하지 않는다는 뜻이다.

트레일의 기록 상태(`OFF/RECORDING/PAUSED`)와 선 표시 설정은 별개라서 선을 숨겨도 서비스 기록은
계속된다. territory도 기본 비표시이며 표시를 꺼도 로컬 claim은 지워지지 않는다.

### Debug replay

debug 빌드의 `지도 기능` 탭에서 1×/5×/10× 가상 경로를 재생할 수 있다. replay는 화면/territory
검증용 fixture이고 실제 산책 서비스의 source가 아니다. 가상 이동 중에는 산책 기록 시작을 막고,
산책 기록 중에는 가상 이동 시작을 막아 mock feed와 서비스 소유 실산책을 한 세션으로 섞지 않는다.
가상 좌표로는 영역을 마킹할 수 없고, 재생이 끝나거나 실패하면 화면 feed는 실제 위치로 돌아온다.
로컬 격자는 H3가 아니며 공개 소유권이나 서버 동기화의 계약으로 보지 않는다.

## 로컬 설정

`local.properties.example`을 `local.properties`로 복사하고 SDK 경로를 고친다. Gradle은
`local.properties` → 프로세스 환경변수 → 레포 루트의 무시된 `.env` 순서로 개발 설정을 읽는다.

```properties
sdk.dir=C\:\\Users\\you\\AppData\\Local\\Android\\Sdk
DAENGS_API_BASE_URL=http://10.0.2.2:8000
DAENGS_NAVER_NCP_KEY_ID=...
```

NAVER Cloud Maps 애플리케이션에서 Dynamic Map을 켜고 Android 패키지
`com.daengs.geo`를 등록해야 한다. NCP key id가 없으면 앱은 설정 안내 표면을 보여준다.

서버 연결:

| 실행 환경 | `DAENGS_API_BASE_URL` | 준비 |
|---|---|---|
| Android 에뮬레이터 | `http://10.0.2.2:8000` | 기본값 |
| USB 실기기 | `http://127.0.0.1:8000` | `adb reverse tcp:8000 tcp:8000` |
| 같은 Wi-Fi 실기기 | `http://<개발 PC LAN IP>:8000` | 서버를 `--host 0.0.0.0`으로 실행 |

평문 HTTP 허용은 debug manifest에만 있다. release 기본 주소는 HTTPS placeholder이며 배포 전에
실제 운영 주소를 넣어야 한다.

## 빌드와 테스트

Android Studio에서 `android/`를 프로젝트로 열거나 다음을 실행한다.

```powershell
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
cd android
.\gradlew.bat testDebugUnitTest lintDebug assembleDebug
```

Foreground Service 실기기 smoke에서는 다음을 추가로 본다.

1. 앱이 보이는 상태에서 `동선 기록 시작` → 산책 알림 생성
2. 홈/다른 앱/화면 OFF 후에도 알림이 유지되고 다시 앱을 열었을 때 trail이 이어지는지
3. 알림의 일시정지/계속 기록/종료가 UI 상태와 동일하게 반영되는지
4. 기록 중 replay가 차단되고 종료 후 replay가 다시 가능한지

debug 화면의 `CTA 확인용 · 반경 100m`는 결과 0곳 상태를 만들기 위한 개발 보조 동작이다.
결과가 여전히 있으면 지도를 빈 지역으로 옮긴 뒤 `이 지역 검색`을 누른다.

## 아직 하지 않은 것

- 이 변경의 실기기 화면 OFF/다른 앱 전환 smoke
- 산책 Room/SQLite 영속 저장, 서버 업로드 주기, process-death 복구
- territory 영속 저장·공개 소유권·사진, 로그인, 오프라인 큐, push
- `/journey` 실측 상세와 지도앱 handoff
- release 배포 설정 (CI 의 unit test + assembleDebug 는 `.github/workflows/ci.yml`)
