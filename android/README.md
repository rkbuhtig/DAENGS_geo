# DAENGS Android 워킹 스켈레톤

`android/app` 단일 모듈이 실제 위치에서 `POST /hospital/search`를 호출하고 NAVER 지도,
마커, 하단 병원 카드, `actions[]`, 안전 통지, 전화 동작을 렌더링한다. 같은 지도에서 연속
현재 위치, 선택형 트레일과 로컬 territory 레이어도 실행한다. 백그라운드 위치 추적은 아직
구현하지 않는다.

## 경계

```text
location/  단발·연속 위치 계약, Fused 제공자, 가상 경로 재생, 연속 구독 하나를 소유하는 tracker
hospital/  HTTP 계약. state와 actions[].edits는 JsonObject/JsonArray로 불투명 왕복
map/shell  단일 MapHost와 제공사 독립 MapScene
map/layers 장소·트레일·territory의 구체적인 렌더 상태
map/provider/naver  MapScene을 NAVER SDK 오버레이로 변환
territory/ 서버 없는 개인 마킹 저장소와 순수 Kotlin 로컬 육각 격자
walk/      표시용 트레일과 독립된 산책 사실 계산 + debug 로컬 미리보기
app        DaengsApplication 조립점. DI 프레임워크 없음
```

앱이 소유하는 위치는 두 개다.

- `deviceLocation`: 센서가 갱신하지만 검색을 자동 실행하지 않는다.
- `searchOrigin`: 서버 state에 들어 있는 현재 검색 기준점이다.

`follow_device` 검색은 요청 시점의 최신 위치를 top-level `origin`에 붙인다. 지도 이동 후
`pinned` 검색은 `set_origin` edit만 보내고 top-level `origin`을 생략한다. 이 규칙은
`SearchRequestBuilderTest`가 고정한다.

연속 위치 갱신은 `feedSample`·트레일·현재 territory 셀만 바꾸고 병원 검색을 자동으로
실행하지 않는다. `deviceLocation`은 실제 기기 fix만 쓰기 때문에 가상 이동 중에도 검색
`origin`은 마지막 실제 위치를 유지한다. 트레일의 기록 상태(`OFF/RECORDING/PAUSED`)와 선 표시 설정은 별개라서 선을
숨겨도 사용자가 시작한 기록은 계속된다. territory도 기본 비표시이며 표시를 꺼도 로컬 claim은
지워지지 않는다. 현재 연속 위치 구독은 Activity가 화면을 벗어나면 중단하며, background 기록은
후속 foreground service가 소유한다.

debug 빌드의 `지도 기능` 탭에서 1×/5×/10× 가상 경로를 재생할 수 있다. 재생 source는 실제
Fused source와 같은 `LocationSource`를 구현하므로 실제로 걷지 않고 현재점·트레일·육각 셀을
관통 검증한다. 재생은 검증 도구라서 사용자가 시작한 기록을 지우지 않고, 피드가 바뀌면 트레일
세그먼트가 끊겨 가짜 좌표와 실제 좌표가 한 선으로 이어지지 않으며, 가상 좌표로는 영역을
마킹할 수 없다. 재생이 끝나거나 실패하면 피드는 실제 위치로 돌아온다. 로컬 격자는 H3가 아니며 공개 소유권이나 서버 동기화의 계약으로 보지 않는다.

가상 이동의 **재생 시간**과 **시뮬레이션 시간**은 분리한다. 10×는 화면에서만 열 배 빠르고,
각 fix의 시각은 1.3m/s로 걸었다고 계산한 시간을 유지한다. 기록을 종료하면 debug 화면에
계산 버전·시간·거리·이동·정지·품질·source가 포함된 `WalkFacts` 로컬 미리보기를 보여준다.
지도 선은 정지 jitter를 버리지만 사실 recorder는 정지 fix를 따로 보존한다. mock 또는 mixed
미리보기는 서버에 저장하거나 업로드하지 않는다. 현재는 device 미리보기도 업로드 경로가 없다.

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

- 실기기 UI smoke test
- 산책 foreground service, 업로드 주기와 판정 소유권
- territory 영속 저장·공개 소유권·사진, 로그인, 오프라인 큐, push
- `/journey` 실측 상세와 지도앱 handoff
- release 배포 설정과 CI
