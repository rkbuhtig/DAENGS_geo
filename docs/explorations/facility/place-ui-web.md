# Android 시설 검색 UI 웹 검토판

Android 실행 환경 없이 현재 표시와 제한사항 보완안을 비교하는 실험이다.
제품 API·검색 정책·Kotlin 코드를 변경하지 않는다. 기본 모드는 현재 앱이다.

## 실행

DB, Docker, Node, 지도 키가 필요 없다. Python 표준 HTTP 서버로 실행한다.

```sh
uv run --no-project --python 3.12 python -m http.server 8765 --bind 127.0.0.1 --directory app/static/place_ui_lab
```

브라우저에서 http://127.0.0.1:8765/ 를 연다.
기존 Geo 앱에서는 `DAENGS_DEV_CONSOLE=true`일 때 `/place-ui-lab/`로 접근한다.
기본 설정에서는 이 경로를 mount하지 않는다.

설치된 Chrome/Edge로 브라우저 동작을 검사할 수 있다. 첫 실행 시 uv가 Playwright
Python 패키지를 내려받지만 별도 브라우저 설치나 재부팅은 필요 없다.

```powershell
uv run scripts/verify/place_ui_lab_browser.py --browser-path 'C:\Program Files\Google\Chrome\Application\chrome.exe'
```

이 검사는 저장한 조건 조합, 카드·마커 선택, 표시 모드, 오류·빈 결과·권한 상태,
응답 문자열 이스케이프, 모바일 너비를 확인한다.

## 현재 앱에서 옮긴 것

기준: `SAJOYO/DAENGS_app@a36a4c9a10556c87efc3fa433c5bc51e74803258`.
스크린샷을 픽셀 단위로 복제한 것이 아니라 Compose 구조·치수·색상·문구를 대응시킨다.
Android의 폰트 배율, 인셋과 지도 SDK 배치는 실기기에서 별도로 확인해야 한다.

| Kotlin 원본 | 웹 대응 |
|---|---|
| `ui/places/PlacesScreen.kt` | 지도 위 홈·내 위치 버튼, 하단 패널 |
| `map/features/places/PlaceDiscoveryPanel.kt` | 최대 430px 패널, 18개 종류 칩, 주차 선호, 평가 집계, 가로 카드 |
| `map/features/places/PlaceCard.kt` | 폭 292px, 모서리 16px, 안쪽 여백 14px, 선택 테두리 |
| `map/features/places/PlaceCardPresentation.kt` | `accessText`, `renderCards`: 현재 입장 평가·주차·운영시간·주소 표시 |
| `place/PlaceModels.kt` | fixture의 기존 응답과 추가 restrictions 필드를 구분하여 소비 |
| `ui/theme/Color.kt` | CSS의 브랜드·표면·기본 텍스트 색상. warning은 웹 가독성을 위해 더 어둡게 사용 |

웹 외곽의 지역·반려견·상태 선택기와 근거 패널은 실험 도구이며 앱에 추가할 화면이 아니다.
지도는 실제 좌표를 근사 배치한 SVG다. 실제 지도 배경·지도 이동 검색·GPS·Android 권한·
네이티브 마커 클러스터링·전화·Journey 호출은 재현하지 않는다. 관련 버튼은 설명만 표시한다.
기본 위치는 저장된 지역의 고정 중심이며 사용자의 위치 권한을 요청하지 않는다.

## 데이터 출처와 한계

`app/static/place_ui_lab/fixtures.json`은 2026-09-05 출시 API
`https://daengapi.weareithero.cloud/v2/places/search`에서 수집한 공개 시설 응답이다.
계정, 토큰, 사용자 반려견, 산책 좌표는 포함하지 않는다. 반려견 조건은 검토용 가상 값이다.

- 중심: 강남역(37.4979,127.0276), 성수역(37.5446,127.0559), 해운대역(35.1631,129.1589), 제주시청(33.4996,126.5312).
- 반경 3km, 종류 cafe/restaurant, 종류별 상한 500.
- 반려견 없음 / small·5kg·3세 / large·30kg·3세 × 주차 선호 끔/켬.
- 4개 지역 × 6조건 = 24개 응답. 서버 정렬·평가·identity를 그대로 보존한다.
- 최초 16개 응답은 같은 날 앞선 검색 조사에서 수집했고, 나머지 주차 조건 8개를 추가 수집했다.
  captured_at_utc는 묶음 작성 시각이며 모든 요청이 동시에 실행됐다는 뜻은 아니다.
- 표본 고유 시설은 45곳이다. 대부분 원천 날짜가 2022-11-30으로, 현재 영업·동반 정책을 보증하지 않는다.
- 미수집 종류는 '미수집'으로 명시한다. 실제 빈 결과와 혼동하지 않는다.
- 현재 표시와 보완안 모두 저장된 응답만 읽는다. 운영 API를 추가 호출하지 않는다.
- loading/error/permission/강제 empty는 실험 상태이며 운영 서버의 실제 장애 기록이 아니다.

## 보완안에서 바뀌는 것

현재 앱은 dog_access를 '입장 조건상 가능'으로 표현하고 상세 제한 평가는 카드에 표시하지 않는다.
보완안은 긍정 라벨을 '크기·체중 조건상 가능'으로 한정하고, 서버의 해당 반려견용 제한 칩을 표시한다.
반려견 조건이 없으면 장소 자체의 칩을 표시한다. partial/raw_only 원문도 함께 보여 준다.
출처 날짜와 추가 확인 안내를 붙인다. compatible과 unknown을 하나의 추천 점수로 합치거나
서버의 후보를 제거·재정렬하지 않는다. 원천 연결이 미검증이면 그 한계를 표시한다.

재현 사례:

- 강남 '정다방 카페': 크기 조건 통과 + 야외만 동반 가능.
- 성수 '구욱희씨': 크기 조건 통과 + 루프탑 외 입장 불가(partial). 칩만으로 원문을 대체하지 않는다.
- '나인페츠 건대점': 크기 조건 통과 + 접종·건강·행동 등 추가 제한.

## Kotlin 반영 전 검토

1. 보완안의 정보량이 292dp 카드와 가로 탐색에 적합한지 확인한다.
2. PlaceModels에 facts.restrictions / evaluations.restrictions를 보존하는 계약을 추가한다.
3. PlaceCardPresentation에서 크기 축과 추가 조건의 문구·톤을 따로 만든다.
4. 현재 fixture의 제한 원문·미상·불일치 사례를 Kotlin 회귀 테스트로 이식한다.
5. 네이티브 지도·접근성·글자 크기·화면 회전은 Android에서 최종 검증한다.

웹 모양이 합의됐다고 검색 정책이나 Android 동작까지 검증된 것으로 간주하지 않는다.
