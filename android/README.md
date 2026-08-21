# DAENGS Android 워킹 스켈레톤

`android/app` 단일 모듈이 실제 위치에서 `POST /hospital/search`를 호출하고 NAVER 지도,
마커, 하단 병원 카드, `actions[]`, 안전 통지, 전화 동작을 렌더링한다. 산책은 진입점만
있으며 백그라운드 위치 추적은 아직 구현하지 않는다.

## 경계

```text
location/  기기 위치. 지금은 foreground 단발 조회, 나중에 산책 tracker가 같은 경계 뒤에 붙음
hospital/  HTTP 계약. state와 actions[].edits는 JsonObject/JsonArray로 불투명 왕복
map/       follow_device/pinned 상태와 NAVER 지도 + 하단 카드
app        DaengsApplication 조립점. DI 프레임워크 없음
```

앱이 소유하는 위치는 두 개다.

- `deviceLocation`: 센서가 갱신하지만 검색을 자동 실행하지 않는다.
- `searchOrigin`: 서버 state에 들어 있는 현재 검색 기준점이다.

`follow_device` 검색은 요청 시점의 최신 위치를 top-level `origin`에 붙인다. 지도 이동 후
`pinned` 검색은 `set_origin` edit만 보내고 top-level `origin`을 생략한다. 이 규칙은
`SearchRequestBuilderTest`가 고정한다.

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
.\gradlew.bat testDebugUnitTest assembleDebug
```

debug 화면의 `CTA 확인용 · 반경 100m`는 결과 0곳 상태를 만들기 위한 개발 보조 동작이다.
결과가 여전히 있으면 지도를 빈 지역으로 옮긴 뒤 `이 지역 검색`을 누른다.

## 아직 하지 않은 것

- 실기기 UI·NAVER 인증 smoke test
- 산책 foreground service, 업로드 주기와 판정 소유권
- 로그인, 로컬 DB, 오프라인 큐, push
- `/journey` 실측 상세와 지도앱 handoff
- release 배포 설정과 CI
