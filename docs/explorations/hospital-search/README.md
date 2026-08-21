# 병원 찾기 — 탐색 갈래

**질문**: 주인이 "어디로 갈지"를 정하는 4축(거리 · 시간 · 종류/규모 · 평가) 중, 리뷰 데이터 없이 어디까지 채울 수 있나. AI는 어디에 끼나.

**고정 축 (안 변함)**: 좌표 하나 → 반경 안 동물병원 → 거리·영업으로 정렬. `app/geo/search.py`. 나머지는 전부 이 위에 얹는 갈래.

| 갈래 | 상태 | 한 줄 |
|---|---|---|
| [two-entrypoints](two-entrypoints.md) | adopted | 챗봇/메뉴 두 진입점, 검색 함수는 하나 |
| [link-out](link-out.md) | adopted | 리뷰는 제공사 페이지를 인앱 브라우저로. 우리가 안 읽음 |
| [google-places](google-places.md) | **rejected** | 별점·리뷰 API 있으나 국내 신뢰도 낮음 |
| [name-tagging](name-tagging.md) | exploring | 사업장명·인허가(면적·종사자)에서 24시/응급/규모 태깅. 공짜 |
| [kakao-category](kakao-category.md) | exploring | 카카오 로컬 `category_name`으로 과목 보강. 미저장 |
| [community-search](community-search.md) | **exploring** | 주인 말투 쿼리 → 네이버 검색 API(카페·블로그·지식iN) → 병원명 추출 → DB 매칭 → 근거 부착 |
| [policy-split](policy-split.md) | **adopted** | 조건을 target(필터)/journey(판정)/view로 분리. 경계는 테스트로 강제 |
| [refine-loop](refine-loop.md) | exploring | 초안 → 대화로 조건 편집 → 재검색. LLM은 툴로 상태만 고침 |
| [condition-schema](condition-schema.md) | exploring | 이용 가능한 조건 전체 펼침. 필터/정렬/표시 역할 분리 |
| [journey-view](journey-view.md) | **adopted** | 카드 눌렀을 때 = 공용 `/journey`. companion(dog/none). 큰길 비율이 비교축 |
| [transport-snapshot](transport-snapshot.md) | exploring | 도보/차량/대중교통을 병원마다 같은 칸에. 도보 장애물은 TMAP, advice는 우리 |
| [homepage-enrich](homepage-enrich.md) | parked | 병원 홈페이지에서 진료시간·과목 온디맨드 추출 |
| [session-record](session-record.md) | exploring | 검색 세션을 서버에 남겨 목록·복원. 조건만 저장(레시피), 제목은 LLM 없이 |

갈래끼리 배타적이지 않다. 여러 개가 같이 adopted 될 수 있음. rejected도 지우지 않는다 — 같은 질문을 다시 안 하려고.
