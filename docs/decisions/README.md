# 결정 기록

확정된 것만. 어느 갈래에서 나왔는지 링크. 갈래 파일은 `../explorations/`에 그대로 남긴다.

| # | 결정 | 이유 | 날짜 |
|---|---|---|---|
| 1 | 백엔드 FastAPI/Python | 팀 스택. Kotlin/Spring 통일안 기각 | 2026-08-19 |
| 2 | 앱은 Android(Kotlin) 전용, iOS 없음 | 산책 = 백그라운드 GPS = 네이티브 필수. 웹/PWA는 화면 꺼지면 위치 끊김. KMP는 백그라운드 위치를 공유 못 하므로 지금 고민 안 함 | 2026-08-19 |
| 3 | 병원/약국 + 산책 = 레포 하나 (`DAENGS_geo`) | 지오 인프라 공유. 팀 타 기능과는 분리 (경계가 사람 단위) | 2026-08-19 |
| 4 | 반려견 프로필은 외부 계약으로 소비 | 원천이 타 담당. `profile_version`으로 변경 감지 | 2026-08-19 |
| 5 | PostGIS, 벡터 검색 안 씀 | 병원 검색은 거리+필터. pgvector와 동거 | 2026-08-19 |
| 6 | 산책 게임 판타지 없음 | "테마 변경"은 기능 폐기 의미였고, 재개하되 현실 기반. 에이전트 = 개의 목소리 | 2026-08-19 |
| 7 | 판정은 코드, LLM은 서술/파싱만 | 보상 인플레·환각 방지. 병원 정보 LLM 생성 금지 | 2026-08-19 |
| 8 | 산책 API는 Agent Router 바깥 | 질문이 없는 스트림. 라우터가 분류할 대상이 아님 | 2026-08-19 |
| 9 | 챗봇 응답 = answer + results + map(preview/deeplink/web_url), 전부 results에서 파생 ([two-entrypoints](../explorations/hospital-search/two-entrypoints.md)) | 텍스트·카드·지도 불일치 방지 | 2026-08-19 |
| 10 | 메뉴 지도는 네이티브, 챗봇은 카드→딥링크 ([two-entrypoints](../explorations/hospital-search/two-entrypoints.md)) | 지도 코드 한 벌, 검색 API 한 벌 | 2026-08-19 |
| 11 | 어댑터는 `static_map_url / geocode / reverse_geocode` 3메서드, 정적지도·지오코딩 제공사 분리 설정 가능 | 백엔드가 제공사를 만지는 곳이 두 군데뿐. 카카오 정적지도 신규(2026-07)로 "섞을 필요"는 약해졌으나 볼륨 대비로 유지 | 2026-08-19 |
| 12 | 영업시간은 `place.hours` JSONB (요일별 구간 + 예외일), 판정은 파이썬 순수함수 | 자정 넘김·예외일·미상(None) 처리를 SQL로 하면 지저분. `open_now` 필터는 넉넉히 가져와 앱에서 거른다 | 2026-08-19 |
| 13 | 정적 지도는 서버 프록시(`/map/static`) | 네이버는 헤더 인증이라 URL만 넘기면 클라이언트가 못 받음 + 키 노출 방지 | 2026-08-19 |
| 14 | 로컬 Python 3.12 고정, uv, `tzdata` 명시 의존 | Windows엔 IANA tz DB 없음 → `Asia/Seoul` 판정 실패 방지 | 2026-08-19 |
| 15 | 리뷰는 링크아웃(인앱 브라우저), 우리가 읽지 않음 ([link-out](../explorations/hospital-search/link-out.md)) | 크롤링 회피. 눈앞까지는 되고 읽는 건 안 됨 | 2026-08-19 |
| 16 | Google Places 기각 ([google-places](../explorations/hospital-search/google-places.md)) | 국내 신뢰도 낮음 (사용자 결정) | 2026-08-19 |
| 17 | 문서는 갈래 구조 (`docs/README.md`) | 한 줄기로 박으면 확정처럼 읽힘. 여러 방향으로 뻗을 수 있게 | 2026-08-19 |
| 18 | LLM은 `utterance` 있을 때만, "말→툴 호출" 번역 한 겹. UI 필터와 자연어는 같은 툴로 수렴 ([refine-loop](../explorations/hospital-search/refine-loop.md)) | 팀 챗봇 관할 분리. LLM 실수 범위를 '조건 잘못 바꿈'으로 한정 | 2026-08-19 |
| 19 | 진입 3종(메뉴=초안 / 딥링크=state 복원 / 재조정=edits·utterance)을 `POST /hospital/search` 하나로 | 엔드포인트 분리 불필요. state 유무로 갈림 | 2026-08-19 |
| 20 | 부스트(특화·근거)는 같은 거리/시간 밴드 안에서만 순서 변경. 필터 아님 | 데이터 있는 병원만 위로 가는 왜곡 방지 | 2026-08-19 |
| 21 | 도보 경로 = TMAP 단독, 폴백은 휴리스틱(시간·거리만) ([transport-snapshot](../explorations/hospital-search/transport-snapshot.md)) | 장애물 주는 API가 TMAP뿐. 틀린 시설정보는 없는 것보다 나쁨 | 2026-08-19 |
| 22 | 도보는 네비가 아니라 **출발 전 한 장**: 이 개한테 걸리는 지점(spots)+한마디, 실제 따라가기는 제공사 앱 딥링크 ([transport-snapshot](../explorations/hospital-search/transport-snapshot.md), research/2026-08-19-dev-console.md) | 검색하는 사람은 모르는 곳에 처음 가는 사람. 원하는 건 "어디가 걸리는지"의 통찰, 도달 과정은 타 지도앱이 잘함 | 2026-08-19 |
| 23 | `/dev` 검증 콘솔(HTML 1파일, Leaflet+OSM). 앱 UI 아님, 운영 비노출 | JSON으론 루프와 길의 감각이 안 보임. 화면에 올려야 뭘 버릴지 정해짐 | 2026-08-19 |
| 24 | **선(폴리라인)이 1급.** 실측 경로는 encoded polyline으로 기본 포함, 상위 N개 선을 지도에 다 그린다. spots는 선 위의 점, 텍스트는 접힌 보조 | 글로 읽고 머릿속에서 재생성하는 건 불편. 선이 있으면 과정을 몰라도 "어디로 가야 하는지"가 펼치지 않고 보인다 (사용자) | 2026-08-19 |
| 25 | **조건을 두 정책으로 분리**: target(어디를 갈까=필터) / journey(어떻게 갈까=판정, 결과를 안 뺌) / view(표시). 타입·툴 그룹·diff·프롬프트까지 전부 분리하고 테스트로 강제 ([policy-split](../explorations/hospital-search/policy-split.md)) | 두 조건이 결과에 하는 짓이 다른데 평평한 한 덩어리라 섞일 위험. 경계를 넘는 건 journey.hard_limit 하나뿐 | 2026-08-19 |
| 26 | **지도·경로를 공용 `journey/`로 분리**, 병원 검색은 가볍게(estimate만), 실측은 `POST /journey`로 카드 눌렀을 때. 약국은 얇은 feature ([journey-view](../explorations/hospital-search/journey-view.md)) | 검색 응답에 경로가 붙어 있는 게 과함. 산책·약국이 같은 journey를 쓴다 | 2026-08-19 |
| 27 | `companion: dog\|none`. 사람만 갈 땐 개 계수·노트·advice·프로필 기본값 전부 빠짐. 병원 dog / 약국 none 기본 | 약국은 대개 혼자 감. 개 요소가 붙으면 이상함 | 2026-08-19 |
| 28 | 계단제외·지하도 피함은 UI 옵션에서 제거. 비교축은 **골목 섞인 추천 vs 큰길 위주**(큰길 비율·큰길 횡단 수). 서울 한정 혼잡도는 안 함 | 실측상 계단·지하는 거의 안 나옴. 큰길은 매번 있음. 지역 한정 기능은 안 넣음 | 2026-08-19 |
| 29 | **policy와 직교하는 `scope` 축 도입**: 수단 선택(walk/car/transit)과 수단별 하위 설정은 계층이 다르다. 도보 옵션·피할 시설은 `scope=walk`, 전체 이동시간은 `scope=any`. 하위 설정 툴이 `preferred_mode`를 몰래 세우지 않는다 ([policy-split](../explorations/hospital-search/policy-split.md)) | 도보 옵션이 차량 판정에 적용되면 안 된다. #25가 journey를 한 덩어리로 묶는 바람에 `avoid()`가 mode를 세우고, `max_min` 하나가 '전체 이동시간'과 '개가 걸어도 되는 시간' 두 뜻으로 쓰였다 | 2026-08-20 |
