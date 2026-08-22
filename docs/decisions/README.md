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
| 30 | **한 값이 여러 뜻이면 타입을 가른다**: `at` → `TimeIntent(kind=depart_at\|arrive_by\|service_at)`, `emergency` → `urgency`(이번 상황) / `emergency_service`(병원의 표방), `night` → `night_service` ([condition-schema](../explorations/hospital-search/condition-schema.md)) | 한 필드에 담으면 소비자가 각자 해석하고 그 해석이 조용히 어긋난다. 실제로 병원 영업 판정은 `target.at`을, 경로 야간 판정은 서버 현재 시각을 봤다 — 같은 요청인데 두 엔진이 다른 시각을 살았다 | 2026-08-21 |
| 31 | **이름 태그는 거르지 않는다.** night·emergency·과목 태그는 `SearchMust`가 아니라 `SearchPrefer` — 순위만 올리고 결과에서 빼지 않는다 ([condition-schema](../explorations/hospital-search/condition-schema.md), [name-tagging](../explorations/hospital-search/name-tagging.md)) | 실측 2026-08-20: 활성 병원 5,457곳 중 night 1 · emergency 2 · ortho 2. 간판 이름 정규식이 유일한 재료다. 이 신뢰도로 `WHERE`를 쓰면 "급해요" 한마디에 결과가 2곳으로 무너진다 | 2026-08-21 |
| 32 | **긴급도는 두 층이다**: 안전 표면(전화 CTA·경고)은 `max(신호)` — 사용자가 못 끈다. 행동 계획(수단 우선·정렬)은 **사용자 명시가 이긴다** ([condition-schema](../explorations/hospital-search/condition-schema.md)) | 한 값으로 합치면 증상 정규식 오탐 하나가 세션 전체를 응급 UI에 가두고 사용자가 내릴 방법이 없다. 반대로 안전 문구를 사용자가 끄게 하면 안 된다. 두 표면은 요구가 반대라서 값도 둘이어야 한다 | 2026-08-21 |
| 33 | **증상에서 과목을 추론하지 않는다.** 사용자의 말은 `target.symptoms`에 그대로 남고, 과목 번역은 커뮤니티 코퍼스가 한다 ([query-rewrite-experiment](../research/2026-08-19-query-rewrite-experiment.md)) | "숨을 헐떡여요" → 심장은 **진단**이고 관할 밖이며([overview](../overview.md)) 우리에게 재료가 없다. 실험에서도 정제한 쿼리는 과목을 못 잡았고 증상 언어가 잡았다 | 2026-08-21 |
| 34 | **근거 조회는 state가 시킨다.** 쿼리를 `target.symptoms`·`specialty`에서 만들고 `utterance`는 못 들어온다. evidence는 순위 권한을 유지하되 밴드(500m/5분) 안에서만 ([evidence-index](../explorations/hospital-search/evidence-index.md)) | 그 턴에 말을 했는지가 순위를 흔들었다 — 발화 턴엔 boost +N, 버튼 턴엔 0. 무상태 계약 위반이다. 권한을 아예 뺄 수도 있었지만 실데이터에서 이름 태그가 거의 비어 있어(#31) 근거가 과목 신호의 본체다 | 2026-08-21 |
| 35 | **요청 계약에 버전과 경계를 박는다**: `state_version`, `extra=forbid`, 전 필드 상·하한, history까지 재귀 검증. 모르는 버전·필드·툴·인자는 조용히 버리지 않고 422 ([condition-schema](../explorations/hospital-search/condition-schema.md)) | 무상태 서버라 state는 서버의 기억이 아니라 **클라이언트가 보내는 입력**이다. 툴에만 클램프가 있어서 state를 직접 보내면 우회됐다 | 2026-08-21 |
| 36 | **엔진은 자기 plan만 받는다.** `resolve_request()`가 state+facts를 한 번 읽어 SearchPlan/JourneyPlan/ViewPlan을 만들고, 검색·경로는 state도 서버 시각도 다시 안 읽는다. 상황이 사용자 설정을 눌렀으면 `trace`로 화면에 말한다 ([condition-schema](../explorations/hospital-search/condition-schema.md)) | 조각을 여러 개 넘기면 결국 누군가 하나 더 끌어다 쓴다. 경계는 규율이 아니라 **볼 방법이 없는 구조**로 막아야 한다 | 2026-08-21 |
| 37 | **undo 의 단위는 툴이 아니라 턴이다.** 되돌림 지점은 `refine()` 이 턴 경계에서 하나만 찍는다. undo 가 낀 턴과 상태가 안 바뀐 턴은 안 찍는다 ([refine-loop](../explorations/hospital-search/refine-loop.md)) | "계단은 빼줘" 한 마디가 툴 두 개(set_mode + set_walk_avoid)라 undo 한 번이 "도보는 유지, 계단 제외만 취소" — 사용자가 한 번도 말한 적 없는 중간 상태를 만들었다. 10칸 스택도 4~5턴이면 찼다 | 2026-08-21 |
| 38 | **추정은 시설을 만들지 않는다.** 폴백(FakeProvider)은 거리·시간·요금까지만 주고 횡단보도·계단·지하보도를 지어내지 않는다. 옵션(no_stairs·main_road)도 숫자를 안 바꾼다 | 결정 #21이 "폴백은 시간·거리만, 틀린 시설정보는 없는 것보다 나쁨"이라 했는데 폴백 자신이 어겼다. 지어낸 시설이 `walk_advice`로 흘러 TMAP이 죽은 날 노령·관절견 경로에 **실측된 적 없는 "계단 1회 — 노령" 경고**가 붙었다 | 2026-08-21 |
| 39 | **`Leg.status` = measured / estimate / unavailable + 강등 이유.** `source`(누가 줬나)와 직교하는 축 — status 는 얼마나 믿을 수 있나. `measured` 는 **진짜 제공사만** 받는다 (fake 는 실측 요청에도 estimate) | 강등이 조용했다. 의도한 추정(목록 미리보기)과 실측 실패가 같은 값으로 나와 구분할 수 없었다. 계산식을 제공사 결과라고 부르는 건 이 레포가 계속 없애온 그 거짓말이다 | 2026-08-21 |
| 40 | **`*_ROUTE_PROVIDER=none` 은 '안 쓴다'는 뜻이다.** 숫자를 만들지 않고 `unavailable`(min·m null)로 낸다 | 예전엔 none 으로 꺼도 폴백이 돌아 1,500원짜리 대중교통 leg 가 나왔다 — 설정이 거짓말이 됐다. 시간을 모르는 곳은 `hard_limit` 에서도 빼지 않는다: 모름은 초과가 아니다 | 2026-08-21 |
| 41 | **제공사가 능력(`route_modes`)을 선언하고, 서버 시작 시 설정과 대조해 안 맞으면 뜨지 않는다** | `car_route_provider=kakao` 는 장애가 아니라 **평시에도 100% 추정**이었다 — KakaoProvider.route 가 자동차 미구현이라 언제나 None 을 준다. 설정 오류가 런타임 강등과 같은 침묵 경로로 합류하면 구분할 방법이 없다 | 2026-08-21 |
| 42 | **가짜 커뮤니티 근거는 기본값이 아니다.** `community_provider` 기본 `none`, `fake` 는 `dev_console` 이 켜져 있을 때만 동작 | fake 는 검색어를 안 읽고 강남 시드 6개를 늘 돌려주는데 근거는 순위를 바꾼다(#34). 부산에서 검색해도 강남 시드가 실제 병원 순서를 흔들었다. 순위 권한 자체는 유지한다 — 실데이터에서 이름 태그가 거의 비어 있어서(#31) | 2026-08-21 |
| 43 | **좌표 없는 활성 시설 복구는 지금 하지 않는다.** 전체의 약 5% 수준이고 PR #6 방식으로 언제든 복구 가능하지만, 정밀도·출처·재적재 검증까지 포함하면 현재 제품 판단에 비해 작업이 크다 | 결손을 잊은 것이 아니라 의도적으로 보류한다. 현재 검색·지도 경험을 먼저 실제 공급자 위에서 검증하고, 커버리지 결손이 제품 판단을 막을 때 다시 연다 | 2026-08-21 |
| 44 | **첫 실제 지도 표면은 네이버 Dynamic Map + Static Map.** 검색은 PostGIS 그대로, 지오코딩·경로·데이터 보강은 이번 선택에 묶지 않는다. `/dev`는 키 누락·SDK 로드 실패 시 OSM으로 폴백 | 공급자를 한꺼번에 싣지 않고 사용자가 직접 만지는 지도부터 실물로 검증한다. 정적 지도는 기존 서버 프록시로 secret을 숨긴다. Web 서비스 URL 불일치는 NAVER 실패 타일로 보일 수 있어 등록·접속 호스트를 일치시킨다 | 2026-08-21 |
| 45 | **CTA는 생성 경로가 아니라 공통 `actions[]` 출력 계약이다.** 룰베이스와 미래 LLM 제안이 같은 틀을 쓰되, action은 여러 `edits[]`를 묶어 기존 refine 검증·diff·턴 단위 undo로 실행한다 ([검색 응답 계약](../contracts/search-response.md)) | 버튼 하나가 `set_mode(walk)`+`set_walk_avoid(stairs)`처럼 여러 툴일 수 있다. 단일 edit면 사용자가 한 번 누른 행동이 여러 undo 칸으로 갈라진다. v0는 LLM 없이 결과 0곳·불명확 질문의 결정론적 제안만 낸다 | 2026-08-21 |
| 46 | **Android 기준 클라이언트를 같은 레포의 `android/` 단일 모듈로 둔다.** 앱은 `deviceLocation`/`searchOrigin`을 분리하고 서버 `state`·`actions[].edits`를 불투명 JSON으로 왕복한다. 첫 절단면은 위치→병원 검색→NAVER 지도·카드→action·전화까지 | 병원·산책이 같은 위치·검색 계약을 쓰고 앱 담당자가 한 명이다. 서버 state를 Kotlin 모델로 재구성하면 서버 필드 추가 때 앱이 깨지므로 화면 필드만 타입화한다. 멀티모듈·산책 service는 실제 두 번째 경계가 생길 때 둔다 | 2026-08-21 |
| 47 | **실제 외부 호출은 공통 Usage Gate를 통과한다.** 기본 `deny-all`, 로컬 실API 검증은 요청·시간당 상한이 있는 별도 `dev` 정책. 무제한 정책과 `dev_console` 결합은 없다. Static Map·실측 경로·OpenAI intent는 자유형 속성 없이 각각 타입으로 고정한다 | 이 레포는 인증을 소유하지 않지만 무엇을 호출하는지와 집행 경계는 소유한다. 상위 서비스가 합쳐질 때 Policy/Ledger만 교체한다. 경로 거부는 기존 진실성 계약의 `estimate/usage_denied`, HTTP 표면은 403/429로 명시한다 | 2026-08-22 |
| 48 | **Android 지도는 단일 `MapHost`에 명시적인 선택형 레이어를 조립한다.** 병원 장소·현재 위치·트레일·territory는 독립 렌더 상태이며, 표시를 꺼도 기록 상태를 바꾸지 않는다. `LocationSource`는 단발 위치와 연속 Flow를 모두 제공하고 `LocationTracker`가 연속 구독 하나만 소유한다 | 병원·산책을 배타 모드로 만들면 산책 중 병원 탐색과 선택형 지도 기능이 깨진다. 가상 `ReplayLocationSource`와 실제 Fused source가 같은 계약을 써야 foreground service가 와도 상위 지도를 다시 짜지 않는다. 첫 territory는 서버/H3 없이 순수 Kotlin 로컬 육각 격자로 감각만 검증한다 | 2026-08-22 |
| 49 | **가짜 근거의 게이트는 `/dev` 콘솔과 분리한다.** `fake` 는 전용 `allow_fake_evidence`(기본 `false`)로만 켜지고 `dev_console` 을 보지 않는다 | #42 는 게이트를 `dev_console` 에 얹었는데 그건 콘솔 **표면**을 여는 스위치다. 하나의 플래그가 "무엇을 보여줄까"와 "무엇이 순위를 흔들까"를 같이 정하면, 콘솔을 보려던 사람이 강남 시드의 순위 오염까지 켜게 된다(#19). 두 축을 나눠 안전장치가 서로의 기본값에 기대지 않게 한다 | 2026-08-22 |
