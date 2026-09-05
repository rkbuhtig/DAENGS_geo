# 영역표시 플레이 실험

**앱 화면을 보고 싶으면 [산책 게임 웹 카피](app-copy.md)**를 연다. 기존 시설 검색 웹 검토판의
프레임·색상과 실제 `WalkScreen.kt` 배치에 게임을 연결한 `app-copy.html`이다.
이 문서의 `index.html`은 판정과 조작을 독립적으로 확인하는 실험으로 유지한다.

소속: [산책 점령 게임 제작 계획](../../../../docs/explorations/walk/territory-production-plan.md).
실제 기기가 없을 때 3단계의 지도·촬영·비동기 판정을 조작하며 확인하는 로컬 스파이크다.
기존 `walk_trace_lab.html`의 위치/상태 조작 방식과 `storyboard_and_regions/viewer.html`의
키 없는 합성 SVG 지도를 참고했다. Naver·Leaflet·장소 조회 API와 무관하게 실행된다.
앱 화면 구조를 재현한 웹 실험이며 Kotlin/CameraX를 실행하거나 실제 GPS·카메라를 검증하지 않는다.

## 실행

Geo 루트에서:

```powershell
uv run python -m http.server 8766 --bind 127.0.0.1 --directory scripts/spikes/territory_production_plan
```

[로컬 실험 열기](http://127.0.0.1:8766). 정적 파일은 이 폴더만 서빙하며
API 키·로그인·외부 지도 타일·DB가 필요 없다. 새로고침하면 점유와 대기열은 초기화된다.

1. 대상 옆으로 이동 → 사진 없이 영역표시 → 인증 촬영 → 샘플 셔터.
2. 사진 확인 중 다른 장소로 이동하거나 점령지 표시를 숨겨 본다.
3. 다음 대표견을 두부로 고르고 새 산책을 시작한다. A로 가서 새 사진으로 탈취한다.
4. 부적합은 같은 시도에서 새 사진, 통신 장애는 같은 capture ID로 재시도한다.
5. GPS 오차/오래된 위치/모의 위치/일시정지로 준비 상태와 촬영 가능 여부를 확인한다.

대표견 선택은 **다음 세션**에 적용된다. 이전 시도의 대표견을 바꾸지 않는다.
사진은 명시적인 샘플이며 파일 업로드나 VLM 호출은 없다. 점유 확정 순서 충돌은 보류로,
미인증 간 무사진 경쟁은 미정으로 노출한다. 이탈·재진입 의무나 점수 정책을 추가하지 않는다.

## 계약과 검증

`claims.mjs`는 APP `TerritoryClaim.kt`/`InMemoryTerritoryClaimRepository.kt`의 핵심 계약을
JS로 재현한다. 원본은 APP [#139](https://github.com/SAJOYO/DAENGS_APP/pull/139),
Dev [#249](https://github.com/SAJOYO/DAENGS_dev/pull/249), 카메라 연결은
APP [#142](https://github.com/SAJOYO/DAENGS_APP/pull/142)다.
`territory-claim-scenarios.tsv`는 APP `app/src/test/resources` 및 Dev `backend/tests/fixtures`와
바이트가 같은 사본이다. 변경 시 세 저장소를 같이 확인한다.

페이지가 열리면 `tests.mjs`가 공통 20단계와 접근/동시 점유 경계 6개를 실행해 결과를 표시한다.
브라우저 자동 검증은 임시 localhost 서버를 열고 완료 후 닫는다. Windows Edge 예시:

```powershell
uv run scripts/spikes/territory_production_plan/browser_check.py --channel msedge
```

Edge가 없으면 Playwright Chromium을 설치하고 `--channel`을 생략한다:

```sh
uv run --with playwright python -m playwright install chromium
uv run scripts/spikes/territory_production_plan/browser_check.py
```

2026-09-05: Edge headless에서 공통 26개, 인증 강화/탈취/부적합 재촬영/사진 재시도,
확인 중 표시 숨김·이동, 취소·오래된 위치에서 셔터 차단, 같은 세션의 복수 장소,
일시정지/모의 위치 차단과 390px 가로 넘침 검사를 통과했다. 데스크톱·모바일 크기의
스크린샷도 확인했다. 결과 파일 기본 경로는 OS 임시 폴더의 `territory-play-lab/`이다.
Orca 내장 브라우저는 런타임 연결 오류로 검사하지 못해 별도 Edge 자동화로 검증했다.

실제 기기에 남는 검증: 카메라 권한·렌즈·EXIF 회전·파일 저장·백그라운드/회전 복귀,
보행 GPS, 진동, Compose 화면 배치. 웹 검증 결과가 이 항목들의 통과를 뜻하지 않는다.
