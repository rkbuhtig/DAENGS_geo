# 테스트 재점검 — 지도와 진행

구조 재편(결정 #67)이 끝났다. 그 다섯 PR 은 전부 **"테스트 본문 수정 0"** 을 완료 조건으로
삼았으므로, 테스트는 새 구조를 한 번도 따라오지 못한 채 import 경로만 갱신됐다. 이 문서는
그 격차를 재고 pass 별로 좁힌 기록이다.

한 번에 다 돌리면 꼼꼼해지지 않는다. 나눠서, 각 pass 마다 세 가지를 묻는다.

    이 테스트가 무엇을 지키나
    어디 있어야 하나
    **무엇을 못 보나**          ← 이번 구조 시리즈에서 네 번 물린 질문이다

## 규모 — Pass 0 스냅샷

**기준 `2331ced` (2026-08-27).** 이 문서의 숫자와 배정은 전부 이 시점의 것이다. 이후
pass 가 진행되고 다른 갈래가 머지되면 총계는 달라진다 — 감사 문서는 현재 상태가 아니라
**시점별 기록**이므로 다시 세지 않고 pass 결과에 변화를 적는다.

397 개 / 49 파일. 디렉토리별로는 `walk` 129 · `discovery` 102 · `facility` 60 ·
`place` 31 · `providers` 32 · `api` 14 · `usage` 9 · 최상위 20.

## 자리 불일치 — 디렉토리 이름이 옛 구조의 화석이다

| 디렉토리 | 실제 검증 대상 | 처분 |
|---|---|---|
| `search/` → `discovery/` | import 1위가 `app.discovery`(38건). `search` 라는 패키지는 없다 | **Pass 1 완료** |
| `walk/` | walk 7파일 + **territory 6** + scene 1 — 코드는 셋으로 갈랐는데 테스트는 한 방 | Pass 2 |
| `facility/` | `geo`+`ingest`+`place` 혼재. #65 가 내부 용어로 격하한 어휘 | **Pass 3 완료 — 해체** |
| `place/` `providers/` `usage/` `api/` | 대상과 대체로 일치 | Pass 4 |

배치 원칙은 **primary owner** 다 — 그 테스트가 주로 무엇을 지키는지를 보고 그 패키지 밑에
둔다. 그래야 "이 테스트 어디 두지"에 구조가 답한다.

**`app/` 트리의 1:1 복제가 목표가 아니다.** 둘 이상의 패키지 **사이 경계 자체가 계약**인
테스트가 있다 — 생산자와 소비자를 한 픽스처로 관통해야 의미가 있는 것들이다. 그런 파일은
주 경계 쪽에 두고 **예외 이유를 파일 docstring 과 이 문서에 명시한다.** 억지로 쪼개면
경계 테스트가 반쪽 두 개가 되어 지키던 것을 잃는다.

통합 테스트가 여러 패키지를 관통할 때의 임시 배치도 마찬가지다 — 최종 소유권을 지금
정하지 않고, 그 패키지를 다루는 pass 에서 함께 본다.

## 커버리지 공백

직접 import 가 없는 모듈 24개를 세었으나, TestClient·함수 호출 경유를 추적하니 대부분
간접 검증이었다. **산책 업로드는 공백이 아니다** — `test_walk_store`(멱등) ·
`test_walk_bundle`(변환) · Android `WalkSessionExporterTest` 셋이 분담하고 그 분담을
docstring 이 적어놨다.

진짜로 아무도 안 보는 것:

| 대상 | 무엇이 안 지켜지나 | 배정 |
|---|---|---|
| ~~`GET /places` (legacy)~~ | — | **#114 가 라우트째 삭제, 공백 소멸** |
| `/anchor/search` | `truncated` 경계 | **Pass 3 완료** |
| `providers.naver` · `kakao` | 좌표 순서·인증 헤더 | **Pass 4.1 완료** (4 에서 절반만) |
| `providers.registry.build_raw_provider` | 키 유무별 선택 | **Pass 4 완료** |
| `journey.handoff` | 딥링크 좌표 순서 | **Pass 4 완료** |
| `usage.http` | 503 분기와 `Retry-After` | **Pass 4 완료** |
| `core.clock` | 결정론·tz 인식 | **Pass 4 완료** |

## 실행 시간 (Pass 4.1 이후)

**1분 48초 → 34.9초.** 느린 원인은 두 종류였고 하나만 테스트 문제였다.

    territory   80.2s → 5.6s    _planted() 픽스처가 산책 50 회를 테스트마다 다시 칠했다
    integration 20.7s → 그대로   _LINK_CROSS 쿼리 자체가 11.6s (facility 33,611 행 자기조인)

`_planted()` 는 `Cellophane`(frozen)만 만들고 소비자는 읽기만 하며 `NOW` 가 고정 상수라
재사용이 안전하다 — `lru_cache` 하나로 끝났다. 같은 파일 안에서 19번, `experience` 에서
11번 호출되고 있었다.

남은 `test_cross_kind_rows_are_neither_linked_nor_collapsed` 12.3s 는 **테스트 구조가
아니라 프로덕션 쿼리가 느린 것**이다(직접 재보니 11.6s). 여기서 픽스처를 줄이면 전역 파생
링크를 실제로 재구축하는지를 못 보게 되므로 건드리지 않는다 — 쿼리 최적화는 별건이다. 조사 결과는 [link-rebuild-cost](2026-08-27-link-rebuild-cost.md) 에 있다.

## Pass 진행

- [x] **Pass 0** — 지도 (이 문서)
- [x] **Pass 1** — `search/` → `discovery/`. 아래 참고
- [x] **Pass 2** — `walk/` 를 가른다. 아래 참고
- [x] **Pass 3** — `facility/` 해체. 아래 참고
- [x] **Pass 4** — 공백 전부. 아래 참고
- [x] **Pass 4.1** — provider 어댑터의 *나가는 요청*. Pass 4 의 자기 기준 미달을 닫는다

### Pass 4.1 결과 — 주장과 검출력을 다시 맞춘다

Pass 4 는 `providers.naver`·`kakao` 를 "완료" 로 체크했는데 **절반이었다.** 리뷰가 짚은 대로
`test_naver_sends_both_apigw_headers` 가 필드만 봤다.

    assert provider._headers == {...}          # 필드가 맞는지

호출부에서 `headers=self._headers` 를 `headers={}` 로 바꿔도 통과한다 — **실제로 돌려서
확인했다. 7개 전부 초록이었다.** 인증이 빠지면 401 인데 우리 쪽 로그엔 "경로 없음" 으로
보이는 종류의 사고다.

Pass 3 의 `kind` 테스트와 **정확히 같은 실수**다. 그때 "쓰기 전에 뒤집어 본다" 를 배웠다고
적어놓고, 같은 PR 안의 다른 파일에서 또 필드만 봤다. 교훈은 파일 단위가 아니라 **단언 단위로**
적용해야 한다.

나가는 요청을 잡는 `_Recorder` 로 다시 쓰고, 그 김에 Pass 4 가 안 본 경로도 닫았다.

    naver.geocode          헤더 실제 전달 · y=위도 · 빈 결과 None
    naver.reverse_geocode  coords="경도,위도" · 헤더 · 지역명 순서 결합
    kakao.reverse_geocode  x=경도 · 헤더 · 도로명 없을 때 지번 fallback

mutation 5종(geocode y/x 뒤집기, reverse coords 뒤집기, 헤더 제거, kakao x/y 뒤집기,
지번 fallback 제거)이 각각 잡히는 것을 확인했다. 헤더 제거는 **전에 0개, 지금 2개**가 죽는다.

### Pass 4 결과 — 공백을 메운다

배정했던 6건 중 `GET /places` 는 **#114 가 라우트째 지워서 공백 자체가 소멸**했다. 나머지
다섯을 메웠다.

    tests/usage/test_usage_http.py        7   403·429·503 분기 · Retry-After · detail 모양
    tests/journey/test_handoff.py         5   제공사별 좌표 순서 · 수단 이름 · 인코딩
    tests/providers/test_map_providers.py 7   naver 경도먼저 · kakao y=위도 · 인증 헤더
    tests/providers/test_registry_build.py 9  키 유무별 선택 · 반쪽 키 · 오타 이름
    tests/core/test_clock.py              2   FixedClock 고정 · SystemClock tz 인식

**`usage.http` 는 완전 공백이 아니었다.** `test_usage_gate` 가 403·429 를 HTTP 로 관통해
확인하고 있었다. 진짜로 아무도 안 밟던 것은 **`request_scope_missing` → 503** 과
**`Retry-After` 헤더** 둘이다. 전자는 "서버가 스코프를 안 열었다"는 우리 잘못이라 4xx 로
내보내면 클라이언트가 자기 요청을 의심한다. 공백을 모듈 단위로 세면 이런 게 안 보인다 —
**가지 단위로 세야 한다.**

반복해서 나온 함정이 하나 있다. **좌표 순서가 원천마다 뒤집힌다.**

    journey.handoff   tmap 만 goalx=경도, goaly=위도   나머지는 위도 먼저
    providers.naver   center = "경도,위도"             우리 LatLng 와 반대
    providers.kakao   응답 y = 위도, x = 경도           이름이 좌표를 안 말해준다

뒤집혀도 URL 도 JSON 도 멀쩡해 보이고 지도에 엉뚱한 데가 그려질 뿐이라 어느 단언도 안
깨진다. 서울에서 실행하면 동해로 간다. 셋 다 이번에 고정했다.

**다섯 파일 전부 음성 대조를 돌렸다** — 좌표 뒤집기, 503→500, Retry-After 항상 달기,
detail 을 문자열로, 반쪽 키 통과 등 12가지 변형을 심어 각각 잡히는 것을 확인했다.
Pass 3 의 `kind` 테스트에서 배운 것을 이번엔 쓰기 전에 적용했다.

`registry` 의 함수 이름이 `build` 가 아니라 `build_raw_provider` 였다 — #82 가 "raw
provider factory 를 이름으로 드러낸다"며 바꾼 것이다. 테스트를 쓰다가 알았다.

### Pass 3 결과

`tests/facility/` 를 해체했다. `facility` 는 결정 #65 가 내부 용어로 격하한 어휘라
디렉토리 이름으로 남길 이유가 없다.

    tests/geo/          hours · pet_axes · icon_groups          순수 규칙
    tests/ingest/       anchor_select · mois_ingest             적재
    tests/place/        place_kind_mapping                      분류 계약
    tests/integration/  facility_layer · facility_ranking
                        · pet_filter                            관통 계약 (신설)

`tests/integration/` 을 새로 만든 이유: 남은 셋은 **적재 → 파생 → 검색을 한 진실로
관통하는지**를 보는 테스트다. `test_pet_filter` 의 docstring 이 그대로 그렇게 적혀 있고
(`pet` 축이 적재→파생→검색까지 한 진실로 흐르는지), `test_facility_layer` 는 재적재 후
id 유지와 두 원천 병합을 본다. primary owner 가 없는 것이 **성격**이므로, 억지로 한
패키지에 배정하지 않고 성격을 이름으로 드러낸다 — 배치 원칙의 "경계 자체가 계약" 예외군이다.

`/anchor/search` 공백도 메웠다 (`tests/api/test_anchor_search.py`). 핸들러가 `limit + 1`
개를 뽑아 초과를 판단하는 구조라 **경계에서만 틀린다** — 정확히 `limit` 개일 때 `truncated`
가 새거나, `limit + 1` 인데 삼키거나. 3·5·6 개를 상한 5 로 조회해 그 전환점을 고정했다.
격리는 좌표로 한다(동해 먼바다 한 칸) — 실적재 48만 행과 안 섞인다.

같이 넣은 `kind` 테스트는 처음에 "필터가 상한보다 먼저 걸린다"고 주장했는데, **SQL 을
filter-after-limit 로 뒤집어도 통과했다.** 4행/상한 10 fixture 로는 순서가 드러나지 않는다.
주장을 "미지정은 전체, 지정하면 그 kind 만"으로 낮췄다 — 이 시리즈가 매 pass 마다 묻는
"무엇을 못 보나"를 **새로 쓴 테스트 자신에게** 적용해서 나온 것이다. 테스트를 늘리는 것보다
주장과 검출력을 맞추는 쪽이 먼저다.

### Pass 2 결과

`tests/walk/` 14파일을 검증 대상으로 갈랐다.

    tests/geo/        test_cells_golden                                   geo.cells 만 본다
    tests/territory/  paint · region · layers · multichain · sheet_cache
                      · region_visit_rate · experience · evidence         8파일
    tests/walk/       bundle · contract · curve · facts · store
                      · encounter                                         6파일 잔류

**`test_walk_encounter` 는 일부러 안 가른다.** scene 판정 테스트 3개가 섞여 있지만, 파일
docstring 이 주제를 "관측(사실)과 판정의 **경계** 고정"으로 선언한다 — 생산자와 소비자를
한 픽스처로 관통하는 것이 이 파일의 존재 이유다. 쪼개면 경계 테스트가 죽는다. 두 진입
경로의 합의를 지키는 `test_ranking` 과 같은 종류다.

**`test_territory_experience` · `test_territory_evidence` 도 함께 옮겼다.** 처음엔 #108(E3a)
이 그 파일을 편집 중이라 보류했는데, #108 이 머지되면서 보류 근거가 사라졌다. 둘 다 주
검증 대상이 `territory.experience` · `territory.evidence` 이고 `walk` 쪽은 픽스처용
`facts`·`models` 만 쓴다. 남겨뒀으면 Pass 2 의 `[x]` 가 거짓이 됐다 — **보류는 근거가
사라지는 순간 재검토해야 하고, 그 재검토를 안 하면 체크박스가 사실과 어긋난다.**

경로 문자열 4건 갱신 — `hex-grid-golden.json` 의 generator 주석 포함. 전부 "그 테스트가
지금 어디 있나"를 가리키는 살아있는 포인터라 갱신했다. 사건 서술(결정문의 옛 경로)과
구분한다.

### Pass 1 결과

`tests/search/` → `tests/discovery/`. 함께 옮긴 것:

    test_personas.py        → tests/profile/     검증 대상이 profile.source · journey.advice
    test_facility_ranking.py → tests/facility/    검증 대상이 api.facility · ingest

**테스트 품질 자체는 깨끗했다.** 비공개 심볼을 찌르는 곳 0, `Companion = str` 시절 가정
잔재 0, `inspect.signature` 세 곳은 전부 의도적 경계 고정이다(계획을 나눈 목적이 "엔진이
남의 축을 못 본다"이므로 시그니처가 곧 계약).

`refine.labels` 만 직접 테스트가 없었는데, `diff` 와 `features/hospital/actions` 가
문장 전체를 비교하므로 간접으로는 덮여 있다. 다만 두 소비자가 대표값 하나씩만 쓰기 때문에
**m/km 경계는 아무도 안 본다** — `test_labels.py` 로 그 경계만 고정했다.

`tests/search` 문자열 참조 3건(`.github/workflows/ci.yml` 주석 포함)도 갱신했다. pytest 가
못 보는 자리라 grep 으로만 잡힌다 — 구조 PR 에서 두 번 물린 것과 같은 종류다.
