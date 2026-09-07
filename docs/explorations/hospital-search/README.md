# 병원 찾기 — 탐색 갈래

**질문**: 주인이 "어디로 갈지"를 정하는 4축(거리 · 시간 · 종류/규모 · 평가) 중, 리뷰 데이터 없이 어디까지 채울 수 있나. AI는 어디에 끼나.

## 현재 검색 입구

현재 공용 앱과 검색 전용 앱은 `POST /v2/places/search`를 연결한다.
[Place v2 계약](../../contracts/place-search-v2.md),
[HTTP 어댑터](../../../app/api/places_v2.py), [검색 구현](../../../app/place/search.py)을 먼저 읽는다.
병원은 같은 Place identity와 검색 경로를 사용하는 kind이며 UI의 병원 바로가기는 유지한다
([결정 #71](../../decisions/2026-08-27-hospital-place-entry.md)).
기존 [app/geo/search.py](../../../app/geo/search.py)는 저장소에 남은 병원 검색 구현으로,
현재 공용 앱의 canonical HTTP 진입과 구분한다. 실행은 [루트 안내](../../../README.md#빠른-실행)를 따른다.

## 탐색 이력

아래 표는 각 갈래의 결정과 배경을 찾는 색인이다. `adopted`나 `verified`가 현재 공용 앱에
그 HTTP 표면이 등록돼 있거나 운영에 배포됐다는 뜻은 아니다. 최신 범위는 각 문서와 후속 결정을,
운영 채택은 [승격 원장](../../promotion-ledger.toml)을 확인한다.

| 갈래 | status | implementation | 한 줄 |
|---|---|---|---|
| [two-entrypoints](two-entrypoints.md) | adopted | verified | 챗봇/메뉴 두 진입점, 검색 함수는 하나 |
| [link-out](link-out.md) | adopted | draft | 리뷰는 제공사 페이지로 넘기고 우리가 읽지 않음 |
| [google-places](google-places.md) | rejected | none | 별점·리뷰 API 있으나 국내 신뢰도 낮음 |
| [name-tagging](name-tagging.md) | adopted | verified | 사업장명·인허가에서 태그·규모 표시. 이름 태그는 기본 부스트 |
| [kakao-category](kakao-category.md) | rejected | none | 보강하려던 `specialty` 축이 #64 로 사라짐 |
| [community-search](community-search.md) | rejected | none | 원천 약관이 파생물 저장을 막는다. 구현 제거 (#63) |
| [evidence-index](evidence-index.md) | rejected | none | 오프라인 근거 인덱스도 합법 원천이 확정되지 않아 중단 (#63) |
| [policy-split](policy-split.md) | adopted | verified | 조건을 target/journey/view로 분리. 경계는 테스트로 강제 |
| [refine-loop](refine-loop.md) | parked | working-skeleton | 상태 편집·툴·undo는 구현됐으나 제품 코어에서 보류 |
| [condition-schema](condition-schema.md) | adopted | verified | context/target/journey/view와 실행 plan 경계를 테스트로 고정 |
| [journey-view](journey-view.md) | adopted | verified | 카드 선택 뒤 공용 `/journey`; 단발 경계만 코어 유지 |
| [transport-snapshot](transport-snapshot.md) | parked | none | 남은 미결은 자동차·대중교통 실측 제공사뿐. 옵션 비교는 #66 기각, 살아 있는 계약은 journey-view 소유 |
| [homepage-enrich](homepage-enrich.md) | rejected | none | 홈페이지 있는 병원이 2차 센터 위주라 커버리지 부족 (#63) |
| [session-record](session-record.md) | exploring | none | 검색 세션을 서버에 남겨 목록·복원 |

갈래끼리 배타적이지 않다. 여러 개가 같이 adopted 될 수 있음. rejected도 지우지 않는다 — 같은 질문을 다시 안 하려고.
