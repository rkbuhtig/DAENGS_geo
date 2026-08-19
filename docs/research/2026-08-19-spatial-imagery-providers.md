# 조사: 산책 스토리보드용 공간 이미지 제공사 (2026-08-19)

> 기능·요금·약관은 바뀐다. 구현과 계약 전 공식 콘솔·약관에서 다시 확인한다.

## 조사 질문

종료된 GPS 동선의 좌표와 대략적인 진행 방향을 이용해, 이동 순서대로 정적 공간 이미지 카드를 만들 수 있는가.

필요 조건:

- 촬영 위치를 알 수 있음
- 360도 파노라마 또는 평면 이미지의 촬영 방향을 알 수 있음
- 촬영일을 알 수 있으면 좋음
- Android 앱에서 정적 카드 또는 뷰어로 합법적으로 표시 가능
- 장면 ID·메타데이터·이미지의 저장 범위가 명확함

## 요약

| 후보 | 360/방향 | 정적 장면 API | 한국 적합성 | 스토리보드 판단 |
|---|---|---|---|---|
| Google Street View | 360, `heading` 지정 | ✅ Static Street View | 커버리지 강함 | 기술적으로 가장 직접적. 호출 과금·캐시 제한 |
| Kakao Roadview | 360, 시점 지정 | 공개 문서에서 미확인 | 국내 커버리지 강함 | 인터랙티브 뷰어·딥링크 후보. Android 사용은 별도 협의 |
| NAVER Panorama | 360, POV 지정 | 공개 문서에서 미확인 | 국내 커버리지 강함 | 웹 뷰어 후보. Android는 WebView 검토 |
| Mapillary | 360/평면, 이미지·시퀀스 메타데이터 | 개별 이미지 조회 가능 | 서울은 구간별 편차 | 정적 카드 실험에 적합. 출처 표시·커버리지 검증 필요 |
| KartaView | 평면 이미지 시퀀스 중심 | 개별 사진 API | 서울 표본이 성김 | 보조 후보. 주력으로 부족 |

`정적 장면 API 미확인`은 기능이 없다고 단정하는 말이 아니다. 2026-08-19 현재 공개 개발자 문서에서 파노라마 뷰어가 아닌 정적 로드뷰 이미지 반환 기능을 찾지 못했다는 뜻이다. 계약·제휴 API는 별도로 존재할 수 있다.

## Google Street View

### 가능한 것

- Street View Static API가 좌표 또는 파노라마 ID와 `heading`, `pitch`, `fov`를 받아 비대화형 이미지를 반환한다.
- Metadata 요청으로 이미지 존재 여부와 파노라마 ID를 먼저 확인할 수 있다.
- Android 앱에서는 서버가 서명한 요청 URL을 내려주고 클라이언트가 이미지를 직접 표시하는 구성이 가능하다.

### 제약

- 결제 계정과 API 키가 필요하며 정적 파노라마 요청마다 과금된다.
- 일반적으로 콘텐츠 사전 수집·색인·장기 캐시가 금지된다.
- 파노라마 ID는 캐시 제한 예외로 영구 저장할 수 있다.
- Google Maps 출처 표시를 가리거나 다른 제공사 콘텐츠와 출처가 모호하게 섞이면 안 된다.
- 당일 산책 사진이 아니라 과거 촬영 이미지다.

### 판단

정적 스토리보드 구현에는 가장 직접적이다. `pano_id + heading + 메타데이터`를 저장하고 화면을 열 때 이미지를 다시 요청하는 방식이 정책과 제품 요구에 가장 가깝다. 영구 앨범처럼 이미지를 자체 보관하는 요구와는 충돌한다.

출처:

- https://developers.google.com/maps/documentation/streetview/overview
- https://developers.google.com/maps/documentation/streetview/policies
- https://developers.google.com/maps/documentation/streetview/usage-and-billing

## Kakao Roadview

### 가능한 것

- Web API `RoadviewClient.getNearestPanoId(position, radius)`로 좌표 반경 안의 가장 가까운 파노라마 ID를 찾을 수 있다.
- `setViewpoint()`로 파노라마의 시점을 지정할 수 있다.
- 좌표나 장소 ID로 카카오맵 로드뷰를 여는 링크가 있다.
- Android SDK v2에도 `RoadView`가 있고 위치·검색 반경·바라볼 위치를 지정할 수 있다.

### 제약

- Android 공식 가이드에 로드뷰 사용은 별도 협의가 필요하다고 명시돼 있다.
- 공개 Web/Android 문서에서 스토리보드 카드에 쓸 정적 로드뷰 이미지 반환 기능은 확인하지 못했다.
- 뷰어 화면을 캡처·저장해 이미지 자산으로 사용하는 것은 허용된다고 가정하면 안 된다.

### 판단

국내 좌표 커버리지와 360도 시야 제어는 매력적이다. MVP에서는 정적 카드 공급자보다 `장면 탭 → 카카오 로드뷰 열기`가 안전하다. 정적 카드나 네이티브 임베드가 핵심이면 사전 협의가 필요하다.

출처:

- https://apis.map.kakao.com/web/documentation/
- https://apis.map.kakao.com/web/guide/
- https://apis.map.kakao.com/android_v2/docs/api-guide/roadview/

## NAVER Panorama

### 가능한 것

- NAVER Maps JavaScript API v3의 `panorama` 서브 모듈로 거리뷰·항공뷰를 표시할 수 있다.
- 좌표를 지정하면 반경 300m 안의 가까운 파노라마를 찾는다.
- `panoId`, 좌표, 주소, 촬영일(`photodate`)과 POV를 읽거나 지정할 수 있다.
- 모바일 웹 브라우저를 지원한다.

### 제약

- 공개 Android 지도 SDK 문서에서는 파노라마 기능을 확인하지 못했다.
- 공개 문서에서 정적 파노라마 이미지 반환 기능은 확인하지 못했다.
- Kotlin 앱 안에서 사용하려면 WebView 또는 별도 웹 화면을 검토해야 한다.

### 판단

국내 커버리지와 촬영일 메타데이터는 좋지만 정적 카드 생성 경로가 불명확하다. 웹 뷰어로 열거나 정식 제공 범위를 문의하는 후보로 둔다.

출처:

- https://navermaps.github.io/maps.js.ncp/docs/tutorial-Panorama.html
- https://navermaps.github.io/maps.js.ncp/docs/naver.maps.Panorama.html
- https://navermaps.github.io/android-map-sdk/guide-ko/

## Mapillary

### 가능한 것

- 거리 이미지·시퀀스·커버리지 타일을 API와 MapillaryJS로 탐색할 수 있다.
- 공식 API 데모는 이미지 ID·시퀀스·360도 여부를 다룬다.
- 개별 이미지를 자체 서버에서 제공할 때도 눈에 보이는 Mapillary 출처와 링크를 요구한다.
- 얼굴과 번호판은 업로드 처리 과정에서 흐림 처리된다.

### 서울 표본

2026-08-19에 서울 중심부 커버리지 지도를 직접 확인했다.

- 세종대로·광화문·을지로 일대에 큰길뿐 아니라 일부 보행로·골목 시퀀스가 있었다.
- 세종대로 표본에서 2022-11-27 촬영 보행자 눈높이 이미지를 확인했다.
- 구간별 밀도·촬영일·화질 차이가 크므로 전국 일관성을 가정할 수 없다.

### 판단

정적 카드와 보행자 눈높이 장면을 빠르게 실험하기 좋다. 다만 360도가 아닌 평면 사진은 촬영 방향이 경로와 맞는 경우에만 써야 하고, 서비스 지역별 이미지 발견률을 먼저 측정해야 한다.

출처:

- https://www.mapillary.com/developer/api-documentation/
- https://mapillary.github.io/api-demo/
- https://help.mapillary.com/hc/en-us/articles/115001770269-An-Introduction-to-Mapillary
- https://www.mapillary.com/app/?lat=37.5665&lng=126.9780&z=17

## KartaView

### 가능한 것

- 공개 거리 이미지 플랫폼으로 좌표 주변 사진과 시퀀스를 조회하는 API가 있다.
- 프레임 단위 사진과 촬영 위치·시퀀스 정보를 탐색할 수 있다.

### 서울 표본

2026-08-19에 서울 중심부 커버리지 지도를 확인했다. Mapillary보다 선이 현저히 성겼고, 을지로에서 확인한 표본은 0.41km·68장·2018-10-19 촬영 시퀀스였다.

### 판단

주력 이미지 원천으로 삼기에는 커버리지와 최신성이 부족하다. 다른 제공사에 이미지가 없는 구간의 보조 후보로만 둔다.

출처:

- https://kartaview.org/doc/photos
- https://kartaview.org/doc/explore-imagery
- https://kartaview.org/map/@37.5665,126.9780,14z

## 구현에 미치는 영향

### 지도 제공사와 이미지 제공사를 분리한다

현재 `MapProvider`는 정적 지도·지오코딩·역지오코딩만 담당한다. 공간 이미지는 생명주기와 정책이 다르므로 채택 전에는 기존 어댑터를 넓히지 않는다.

별도 경계 후보:

```text
SceneProvider
- find_candidates(position, radius, captured_after?)
- scene_metadata(scene_id)
- display_ref(scene_id, heading, size)
```

`display_ref`는 반드시 이미지 파일 URL이라는 뜻이 아니다. 제공사 정책에 따라 서명된 단기 URL, 클라이언트 SDK용 ID, 뷰어 딥링크가 될 수 있다.

### 저장은 메타데이터 우선

공통 저장 후보:

- 제공사와 장면 ID
- 촬영 좌표·방향·촬영일
- 경로 지점과의 거리
- 요청한 표시 방향
- 출처 표시 문자열 또는 링크
- 제공사별 캐시 정책

이미지 바이너리는 명시적으로 허용된 경우에만 저장한다.

## 다음 검증

- [ ] 익명화한 원형·왕복·교차 경로 표본 준비
- [ ] 후보 제공사별 경로 회랑 이미지 발견률 측정
- [ ] 360도와 평면 사진의 방향 통과율 비교
- [ ] 장면 카드 3~8장 생성 시 호출 비용 계산
- [ ] 한국 Android 앱에서 허용되는 표시·캐시·출처 표기 방식 제공사 문의
- [ ] 사용자 평가: `내가 지나온 길처럼 느껴지는가`
