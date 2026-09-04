# 산책 GPS·점령지 Lab — 설계와 인수인계

> 작성: 2026-09-04. 구현 기준: `1e87ff0`.
> 문서 보관: 개인 `rkbuhtig/DAENGS_geo`. 구현 위치: `SAJOYO/DAENGS_APP`의 `feat/walk-territory-lab`.
> 이 문서 추가는 팀 APP 저장소 변경이나 구현 코드의 Geo 역이관이 아니다.
> 이 문서는 이 브랜치의 상태다. dev/main에 반영되었다는 뜻이 아니다.

## 1. 다른 컴퓨터에서 이어받을 때 먼저 읽을 것

1. [APP CLAUDE.md](https://github.com/SAJOYO/DAENGS_APP/blob/1e87ff0e9dd0f6883957bb6bb5599842726f71fd/CLAUDE.md): 저장소 작업 규칙.
2. 이 문서: 목적, 설계 결정, 코드 위치, 다음 작업의 경계.
3. [APP 사용·검증 기록](https://github.com/SAJOYO/DAENGS_APP/blob/1e87ff0e9dd0f6883957bb6bb5599842726f71fd/docs/walk-gps-lab.md): 조작법, 수동 실험 순서, 기존 검증 결과.
4. [APP README.md](https://github.com/SAJOYO/DAENGS_APP/blob/1e87ff0e9dd0f6883957bb6bb5599842726f71fd/README.md): 현재 JDK/SDK·지도 키·빌드/설치 설정.

APP 링크는 위 구현 커밋에 고정했다. 후속 구현을 시작할 때는 해당 브랜치의 최신 diff와
적용되는 `CLAUDE.md`를 다시 확인한다. Geo의 `android/`와 APP의 `app/`는 다른 Gradle 프로젝트다.

**작업 방식에 대한 사용자 지시:** 팀 릴리즈 작업과 분리하기 위해 같은 feature 브랜치에만
커밋·push한다. PR을 새로 만들거나 dev/main에 머지·배포하지 않는다. 후속 작업자가 일반적인
draft PR 규칙을 적용해 임의로 PR을 열지 않도록 주의한다. 백엔드의 main 승격도 이 작업의
완료 조건이 아니며, 향후 서버 연결은 별도 합의한 개발 환경을 대상으로 한다.

문서 자체는 사용자 요청에 따라 개인 Geo에만 올린다. 현재 문서 브랜치는
`docs/walk-territory-lab-handoff`이며 PR·main 직접 변경 없이 보관한다.

이 문서는 설계 기록이지 후속 전체 구현의 자동 승인 목록이 아니다. 아래의 '제안'과
'미정'은 다음 작업 전에 사용자와 범위를 확인한다.

### Geo의 다른 실험과의 관계

- [Android replay adapter](../explorations/walk/android-replay-adapter.md): 이 APP Lab이 소비하는 입력의 생산자. JSON/GPX/ADB의 보존·손실 경계는 여기서 읽는다.
- [점령지 게임 탐색](../explorations/walk/territory-site-game.md): 실제 촬영·점령 권위에 관한 별도 가설. APP의 debug 미리보기가 이 계약을 구현했다고 보지 않는다.
- [스토리보드·행동 개인화 인수인계](2026-09-04-walk-personalization-handoff.md): 다른 작업에서 진행하는 공간 일기/프로필 실험이다. 이 문서의 산책 중 GPS·접근 UX와 범위를 혼동하지 않는다.

## 2. 무엇을 만들고 있는가

목표는 GPS 파일을 별도 뷰어에서 보여주는 것이 아니다. **기존 산책 지도에서 실제 산책
상태를 시작하고, 위치가 연속으로 변하면서 점령지 접근·도착·액션·이탈을 시험하는 것**이다.
에뮬레이터에서 위치가 고정된 채로 산책을 시작하면 알 수 없던 UX를 실내에서 반복해 본다.

사용자가 확인하려는 질문은 다음과 같다.

- 점령지에 가까워지는 과정과 도착 가능 상태가 지도에서 읽히는가?
- 경계에서 GPS가 흔들려도 버튼·색이 과도하게 깜빡이지 않는가?
- 도착 후 액션을 시작한 사용자가 사진을 찍는 동안 위치에 계속 묶이지 않을 수 있는가?
- 반경을 벗어난 사실과 이미 점령한 사실을 혼동하지 않는가?
- 같은 입력으로 산책 경로 기록과 행동 기록도 함께 실험할 수 있는가?

장기적으로는 공간 일기와 연결되지만, **이 브랜치는 일기 지도 재설계나 공간 분석 이관을
한꺼번에 하는 브랜치가 아니다.** 먼저 산책 중 한 바퀴의 상호작용을 검증한다.

## 3. 현재 완료 범위와 미완료 범위

| 영역 | 현재 구현 | 아직 하지 않은 것 |
| --- | --- | --- |
| GPS 입력 | Geo replay JSON 가져오기, 내장 합성 예제, 1배속 연속 재생 | 배속 UI, 다중 chain/lifecycle 자동 재현, delivery 장애 주입 |
| 산책 | 기존 시작·일시정지·재개·종료 경로와 별도 실험 Room 기록 | 실험 이력 전용 화면, 프로세스 종료 후 재생 복구 |
| 점령지 | 경로 중간 표본의 가상 지점 하나를 기존 조회 구조로 표시 | 실제 서버 점령지와 실험 소유권 결합 |
| 접근 | 거리·위치 품질·구간 시각을 이용한 debug 판정 | 제품 인증 정책 확정, 서버 도착 영수증 |
| 액션 | 사용자가 여는 점령 표시 미리보기 확인창 | 카메라, 사진 업로드, 실제 인증 API 호출 |
| 소유 표시 | 화면 메모리의 `ownedPreview`, 독립된 마커 배지 | 영구 소유권 원장, 앱 재시작 복원, 경합·중복 처리 |
| 지도 | 10m/12m 원, 도착 강조, 반경 보기·내 위치 복귀 | 최신 수정의 실제 Naver 화면 검증 |
| 격리 | debug source set, 별도 DB, 실험 sync/delivery 차단 | 실험을 제품 기능으로 승격하는 작업 |

`내 점령 · 실험`은 소유권이 서버에 저장되었다는 뜻이 아니다. 도착 판정도 제품 인증을
대체하지 않는다. 이 경계를 UI 문구와 후속 개발에서 계속 유지한다.

## 4. 핵심 설계 결정과 이유

### 4.1 기존 흐름을 재사용하고, 실험 입력과 저장을 격리한다

```text
Geo replay JSON / 내장 합성 예제
  → ReplayTrace 검증 → TraceLocationSource
  → 선택된 WalkRuntime
      → 기존 WalkRoute / WalkTrackingService / WalkFixWriter
      → 실험 Room: daengs_walk_lab.db (서버 동기화 없음)
      → 최신 표본 + 산책 상태 → TerritoryLabSession → 지도 원·카드·미리보기
```

일반 runtime을 전역으로 가짜 runtime으로 바꾸지 않는다. 현재 산책 화면과 서비스가 같은
선택을 사용하고, 일반 홈·기록·WorkManager는 일반 runtime을 계속 쓴다. 일반 DB는
`daengs_walk.db`, 실험 DB는 `daengs_walk_lab.db`다. 실험 DB와 부속 파일은 OS 백업/이전에서도
제외한다. `WalkSync(enabled = false)`와 `NoLabDelivery`로 직접 sync와 예약 delivery를 막는다.

실험 산책의 날씨 stamp 수집을 생략하며, 화면에 남은 날씨는 합성 위치·시각의 환경 증거가
아니다. 실험 점령지 조회도 가상 저장소를 쓴다. 다만 **앱 전체의 네트워크를 끄는 모드가
아니다**. 지도 타일 및 다른 일반 앱 기능까지 오프라인이라고 주장하지 않는다.

모드/파일 교체는 시작 요청부터 서비스 종료·저장 flush 완료까지 막는다. 기록 도중 입력을
바꿔 일반/실험 데이터가 섞이거나, 서비스와 화면이 다른 입력을 보는 상황을 방지한다.

### 4.2 도착·액션 진행·소유 결과는 연결되지만 별개다

| 상태 축 | 현재 표현 | 수명/의미 |
| --- | --- | --- |
| 접근 | `TerritoryApproach.status` | 최신 GPS와 현재 산책 구간으로 계속 계산 |
| 액션 진행 | `pendingPreview` | 사용자가 도착 상태에서 시작한 확인 흐름 |
| 소유 결과 미리보기 | `ownedPreview` | 확인 후 화면 메모리에 남는 별도 표시 |

반경 진입은 좋은 사건이므로 민트색으로 강조한다. 위험을 뜻하는 빨간색으로 표현하지 않는다.
진입만으로 액션을 열거나 소유 상태를 저장하지 않는다. 확인한 소유 표시는 보라색 배지로
분리하며, 이후 반경 밖으로 나가 원이 회색이 되어도 배지는 남는다. 색만으로 구별하지 않고
문구와 버튼 상태도 함께 바꾼다.

화면 재생성/이탈, 파일·모드 변경, 초기화 때 소유 미리보기가 사라질 수 있다. 같은 화면에서
산책이 끝나는 것만으로 지우지는 않는다. 이는 의도된 실험 수명이며 영구 저장 버그가 아니다.

### 4.3 정확도를 거리에 더해서 사용자를 밀어내지 않는다

현재 임시값의 원본은 `ApproachExperiment`다. 제품 확정값으로 복제하지 않는다.

| 항목 | 임시 규칙 |
| --- | --- |
| 첫 진입 | 거리 ≤ 10m |
| 이미 도착한 상태 유지 | 거리 ≤ 12m |
| 위치 정확도 | 유효한 accuracy ≤ 25m |
| 표본 나이 | monotonic 기준 ≤ 8초 |
| 현재 구간 | capture 시각이 `activeSinceRealtimeMillis` 이전이면 거절 |
| 산책 상태 | RECORDING일 때만 도착 가능 |

거리 7m·정확도 4m는 다른 조건이 맞으면 도착 가능하다. `거리 + 정확도 ≤ 10m`를 쓰지 않는다.
다만 모든 위치를 믿는 것도 아니다. 누락/비정상/미래/오래된 표본은 위치 대기,
부정확한 표본은 정확도 확인 상태로 둔다. GPS가 새로 오지 않아도 250ms마다 나이를 갱신한다.

처음부터 11m에 있으면 밖이다. 9m로 들어왔다가 11m로 흔들리면 도착을 유지한다.
위치 품질 상실 또는 산책 구간 변경으로 도착을 잃으면 이전의 12m 유지 권한도 이어지지 않는다.
짧게 pause/resume했을 때 아직 8초 이내인 **이전 구간 GPS**가 도착을 되살리지 않도록
구간 시각을 별도로 검사한다. 화면이 중간 pause 상태를 놓쳐도 구간 변경으로 감지한다.

### 4.4 액션 시작 순간은 검사하되, 현재 미리보기를 인증 영수증으로 취급하지 않는다

`beginPreview`는 클릭 순간 최신 상태를 다시 검사한다. 마지막 화면 갱신 이후 GPS가
낡았으면 시작할 수 없다. 열린 확인창은 같은 기록 구간이면 이후 위치가 멀어졌어도
확인할 수 있다. 취소·일시정지·종료·구간 변경은 진행 중인 확인을 무효화한다.

이 흐름은 '사진을 찍는 동안 계속 동일 위치에 서 있어야 하는가'를 논의하기 위한 UX 대역이다.
서버가 보증하는 시작 증거, 유효기간, 사진과의 연결은 **아직 설계·구현되지 않았다**.
현재 boolean을 제품의 인증 토큰으로 재사용하지 않는다. 서버의 기존 mock 거절이나 인증
정책도 이 브랜치에서는 변경하지 않았다. 실제 연결 시 최신 Dev 계약을 다시 조사한다.

### 4.5 표시가 작다고 실제 반경을 키우지 않는다

10m 원은 전체 지도 배율에서 마커/아바타보다 작을 수 있다. `반경 보기`를 사용자가 누르면
Naver 미터/dp 투영식과 실제 아이콘 크기로 배율을 계산한다. 안쪽 원 지름이 큰 아이콘보다
32dp 넓게 보이도록 하되 zoom은 13~21로 제한한다. 아이콘이나 10m/12m 자체를 키우지 않는다.

초점은 지점 중심에 고정하고 이후 GPS 이동이 카메라를 빼앗지 않는다. `내 위치`는 다시
사용자 추적으로 돌아간다. 같은 지점을 반복해 눌러도 반응하도록 `centerRequestId`를 쓴다.
지도 모드가 점령 지도가 아니거나 현재 조회한 지점이 아니면 초점 요청을 받지 않는다.
수식 테스트 통과만으로 실제 기기에서 원이 잘 보인다고 판정하지 않는다.

## 5. 코드 찾기와 변경 경계

아래 경로는 **APP 저장소 루트 기준**이다. Geo 안에서 같은 경로를 찾거나 코드를 새로 만들지 않는다. 파일명이 같은 debug/release 진입점에 주의한다.

| 위치 | 책임 |
| --- | --- |
| `app/src/debug/java/com/daengs/app/walk/lab/ReplayTrace.kt` | JSON 계약·크기·표본·시각·chain 검증 |
| 같은 디렉터리 `TraceLocationSource.kt` | 1배속 capture 재생, cursor/남은 간격, 현재 시계 rebasing |
| 같은 디렉터리 `WalkLab.kt` | runtime 선택, 별도 DB, 서비스 gate, sync/delivery 차단 |
| 같은 디렉터리 `WalkLabRoute.kt` | 파일 선택 패널, 기존 화면 연결, 상태 갱신, 액션 wiring |
| 같은 디렉터리 `TerritoryApproach.kt` | 실험 정책, 가상 저장소, 세션 상태, scene 장식 |
| 같은 디렉터리 `TerritoryApproachCard.kt` | 도착 카드·확인창·Preview |
| 같은 디렉터리 `TerritoryFocus.kt` | 실제 반경을 유지하는 확대 배율 |
| `app/src/release/java/com/daengs/app/walk/lab/WalkLab.kt` | 일반 runtime/화면으로 연결하는 release 대역 |
| `app/src/main/java/com/daengs/app/ui/walk/` | 선택적 카드/scene 연결, 지점 focus 액션, 카메라 추적 |
| `app/src/main/java/com/daengs/app/map/shell/MapScene.kt` | 선택적 반경 표시 데이터 |
| `app/src/main/java/com/daengs/app/map/provider/naver/NaverMapSurface.kt` | 원 두 개와 카메라 요청 렌더링 |
| `app/src/main/java/com/daengs/app/walk/` | 기존 서비스·기록 경로와 runtime 선택 연결 |
| `app/src/debug/assets/walk_lab/walk-and-stop.json` | PC 밖에서도 바로 실행할 수 있는 내장 합성 경로 |

release에서 debug 파일·패널·parser·asset은 빠지지만 **main 변경이 전혀 없는 것은 아니다**.
일반 기록/서비스에 필요한 선택 지점, 비활성 기본값을 가진 표시 데이터와 주입 지점은 남는다.
격리 회귀를 볼 때 debug 디렉터리만 검사하지 말고 이 공통 경계도 함께 본다.

도메인 방향은 유지한다. Walk는 산책 세션·위치·행동의 발생 맥락을 다루고, Place는 장소/시설
정보를 재사용하는 경계이며, Journey는 여정/점령의 제품 의미를 검토할 경계다. 이 문서는
그 이름만으로 서버 테이블 소유권을 새로 확정하지 않는다. 실제 점령 저장 연결 때 최신 Dev의
기존 책임·API를 먼저 확인하고, Walk에 별도 점령 원장을 중복으로 만들지 않는다.
강아지/산책 귀속도 기존 Dev 결정을 따른다. 여기서 다견 모델을 별도로 재설계하지 않는다.

## 6. GPS 입력 지원 범위

입력은 Geo 생성기의 `walk-location-replay-v1` JSON이다. Geo 저장소 전체를 실행하지 않아도
내장 예제로 APP 실험을 시작할 수 있다. 임의의 GPX나 좌표 배열을 바로 읽는 파서는 아니다.

- 최대 2 MiB, 표본 2~20,000개, offset은 0~24시간 범위다.
- 표본 id는 중복 불가, offset/sequence는 증가해야 하며 지연·나노초 offset 일관성을 검사한다.
- 단일 chain, 빈 `control_events`, `delivery_applied=false`, `is_mock=true`만 허용한다.
- receipt의 표본 개수·누락 개수 일관성도 검사한다. 지원하지 않는 사건을 조용히 버리지 않는다.
- 실제 재생 시점의 wall/monotonic 시계로 맞춘다. 과거 시나리오 날짜의 날씨를 재현하는 기능이 아니다.
- GPS 신호 정지는 새 표본을 멈춘다. 오래된 표본을 새 표본처럼 재발행하거나 보간하지 않는다.
- 산책 pause/resume은 재생 cursor와 남은 간격을 보존한다. 새 산책 시작은 첫 표본부터다.
- 재생 끝은 산책 일시정지이고 자동 최종 저장이 아니다. 사용자가 기존 종료 버튼을 누른다.
- 기존 50m/60초 산책 인정 기준은 그대로라 짧은 경로는 폐기될 수 있다.

## 7. 다른 PC에서 실행하는 절차

기존 checkout에 미커밋 작업이 있다면 먼저 보존한다. 아래는 **새 디렉터리**에서 이어받는 예다.

```bash
git clone --branch feat/walk-territory-lab https://github.com/SAJOYO/DAENGS_APP.git DAENGS_APP-walk-lab
cd DAENGS_APP-walk-lab
git status --short --branch
git log -5 --oneline
```

1. Android Studio에서 프로젝트를 열고 README 및 Gradle 설정에 맞는 JDK/SDK를 준비한다.
2. `local.properties`의 `sdk.dir`은 새 PC 경로로 설정한다. 이전 PC 절대경로를 복사하지 않는다.
3. 실제 지도에는 `daengs.naverMapClientId` 또는 환경변수 `DAENGS_NAVER_NCP_KEY_ID`가 필요하다.
   `daengs.naverMapStyleId`는 선택 사항이다. 로그인/일반 서버 왕복이 필요하면 README에 따라
   `daengs.kakaoNativeAppKey`, `daengs.apiBaseUrl` 등도 별도로 준비한다.
4. 설정·키는 승인된 팀 전달 경로로 받고 커밋하지 않는다. 이 인수인계 문서에 비밀 값은 기록하지 않는다.
   키 없이 빌드가 된다는 사실은 지도 타일 인증이나 서버 연결이 된다는 뜻이 아니다.
5. 테스트용 AVD/기기를 명시적으로 고른다. 기존 사용자 앱/데이터를 무심코 덮어쓰거나 지우지 않는다.
   실험 DB가 별도여도 APK 설치 대상까지 별도 앱이 되는 것은 아니다.
6. debug 빌드 후 설치 결과를 확인하고 [APP 수동 실험 순서](https://github.com/SAJOYO/DAENGS_APP/blob/1e87ff0e9dd0f6883957bb6bb5599842726f71fd/docs/walk-gps-lab.md#수동-실험-순서)를 수행한다.
   외부 파일 없이 `예제`로 시작 가능하다. release 빌드에는 GPS 실험 진입점이 없다.

이전 PC의 `work/emulator-review`는 실패한 임시 AVD 진단 산출물이며 Git 밖에 있다.
옮겨야 하는 실행 의존성이 아니다. APK·로컬 DB·이전 대화·그 PC의 Downloads 없이도
소스와 내장 fixture, 새 PC 설정으로 재시작할 수 있도록 구성했다.

## 8. 검증 현황과 다음 검증의 범위

2026-09-04의 기존 결과이며, 이 문서 추가만으로 테스트를 다시 실행했다고 해석하지 않는다.

- 재개 구간/접근·카드 회귀: 24개 통과.
- 배율·카메라·ViewModel·카드 회귀: 23개 통과. 앞 결과와 중복이 있으므로 합산하지 않는다.
- debug APK 빌드와 release Kotlin 컴파일 성공. 전체 suite는 실행하지 않았다.
- 실제 Naver 원 가시성, 실제 서비스·행동·종료 왕복은 **미완료**다. 이전 임시 AVD는
  부팅 지연/비정상 종료로 APK 설치까지 가지 못했다. 기존 설치본은 보존했다.

다음 명령은 **Geo가 아닌 APP checkout 루트**에서 실행한다. 변경 diff와 테스트 설정을 먼저 보고 아래에서 해당 경계만 선택한다. Windows는
`./gradlew.bat`, macOS/Linux는 `./gradlew`를 사용한다.

접근·구간·카드를 바꾸는 경우:

```bash
./gradlew :app:testDebugUnitTest --tests 'com.daengs.app.walk.lab.TerritoryApproachTest' --tests 'com.daengs.app.walk.lab.TerritoryApproachCardTest'
```

반경 배율·카메라 연결을 바꾸는 경우:

```bash
./gradlew :app:testDebugUnitTest --tests 'com.daengs.app.walk.lab.TerritoryFocusTest' --tests 'com.daengs.app.ui.walk.WalkCameraFocusTest' --tests 'com.daengs.app.ui.walk.WalkViewModelTest' --tests 'com.daengs.app.walk.lab.TerritoryApproachCardTest'
```

입력/격리를 바꾸면 `ReplayTraceTest`, `TraceLocationSourceTest`, `WalkLabIsolationTest`,
`LabPanelTest` 중 해당 클래스를 고른다. 공통 서비스·sync 경계까지 바꾸면 기존
`com.daengs.app.walk.WalkTrackingTest`, `com.daengs.app.walk.sync.WalkSyncTest`,
`com.daengs.app.walk.sync.WalkDeliveryTest`, `com.daengs.app.ui.walk.WalkLocationOwnershipTest`도
영향에 따라 명시적으로 선택한다. 코드/source set 변경 검증에는 필요에 따라
`:app:assembleDebug :app:compileReleaseKotlin`을 추가한다. 문서 변경에 전체 suite를 돌리지 않는다.

수동 확인에서 최소한 다음 증거를 남긴다.

- 기기/밀도/방향, 빌드 커밋, 사용한 시나리오.
- 반경 보기 전후 원·아이콘 가시성, 반복 초점, 내 위치 복귀.
- 접근 시 민트 상태, 진입 시 자동 창이 안 뜨는 것, 이탈 후 소유 배지 유지.
- GPS 정지 8초 초과 시 도착 해제, 짧은 산책 pause/resume 후 새 GPS 전까지 대기.
- 확인창 취소/구간 변경, 지도 목적 전환, 종료 후 일반 모드 복귀와 데이터 격리.

스크린샷은 앱이 전면인지 먼저 확인한다. 화면 확인 결과와 JVM 결과를 별도로 기록한다.

## 9. 다음 작업 제안과 아직 확정하지 않을 것

**우선 제안은 기능 확장보다 설정된 테스트 기기에서 한 사이클을 닫는 것이다.**

1. 내장 예제로 `접근 → 도착 → 미리보기 취소/확인 → 이탈 → 종료`를 실제 지도에서 확인한다.
2. 관찰된 UX 문제만 좁게 고친다. 원이 안 보인다고 인증 반경부터 키우지 않는다.
3. 그 결과를 가지고 실제 촬영/저장 연결의 작은 작업 범위를 사용자와 정한다.

실제 연결을 선택하면 서버의 기존 점령지·사진 인증·소유 기록 계약을 먼저 확인한다.
그때 다룰 질문은 다음과 같다. 아래는 **검토 항목이지 확정된 신규 계층/API 설계가 아니다**.

- 액션 시작 시 위치 증거와 촬영 시점/유효기간을 어떻게 연결할 것인가?
- 어느 산책·강아지·사용자·점령지에 귀속되는가? 기존 Dev 정의를 어떻게 재사용하는가?
- 사진 업로드/소유 기록 중 하나만 성공하거나 응답이 유실되면 어떻게 재시도할 것인가?
- 앱의 대기 상태와 서버 확정 소유 상태를 어떻게 구분하며 중복 쓰기를 막을 것인가?
- 다른 사용자의 변경 등 경합과 앱 재시작 후 복구를 어느 기존 경계에서 처리할 것인가?

산책 증거 저장과 점령 소유 저장은 무관한 두 시스템으로 설계하지 않는다. 그렇다고 이 Lab의
메모리 상태와 실제 원장을 하나로 합치지도 않는다. 기존 계약을 재사용해 둘의 연결과 실패
처리를 함께 정한다. 다견 정책, 새 범용 이벤트 프레임워크, 전체 공간 일기 이관을 동시에
확정하려고 범위를 넓히지 않는다.

## 10. 구현 이력과 이어받는 사람에게 남길 판단

| 커밋 | 내용 |
| --- | --- |
| `a465373` | 기존 산책 흐름에 격리된 debug GPS 재생 연결 |
| `1b53f86` | 가상 점령지·접근 반경·점령 표시 미리보기 |
| `86955a4` | 재개 이전 GPS 및 이전 구간 pending 상태가 되살아나는 문제 수정 |
| `1e87ff0` | 반경 보기 배율·지점 초점·내 위치 복귀와 회귀 테스트 |

핵심은 'GPS가 움직인다'보다 '움직임이 제품 안에서 어떤 의미로 보이는가'였다.
수식이 보수적이라는 이유만으로 UX가 옳지는 않고, 원을 정확히 그렸다는 이유만으로 사용자가
볼 수 있는 것도 아니다. 기존 화면을 재사용한 덕분에 이 차이를 드러낼 수 있었다.
다음 작업도 추상화를 더 쌓기보다 한 사이클의 실제 관찰을 먼저 남기는 쪽을 권한다.
