# 기록별 주변 정보 수집

합성 사용자 기록 + 공급자 응답. LLM 호출 없음.

실제 HTTP 요청 0회 · 캐시 재사용 6개 · 조회 그룹 6개

| 기록 | 종류 | 자료 | 상태 | 반환 항목 | 사유 |
|---|---|---|---|---|---|
| gangnam-behavior-01 | behavior | space.park | known | 1 | — |
| gangnam-behavior-01 | behavior | space.river | partial | 0 | unusable_source_rows |
| gangnam-behavior-01 | behavior | space.facility | partial | 30 | projection_limit |
| gangnam-behavior-01 | behavior | environment.weather | unavailable | — | http_403 |
| gangnam-note-01 | note | space.park | known | 1 | — |
| gangnam-note-01 | note | space.river | partial | 0 | unusable_source_rows |
| gangnam-note-01 | note | space.facility | partial | 30 | projection_limit |
| gangnam-note-01 | note | environment.weather | unavailable | — | http_403 |
| gangnam-photo-01 | photo | space.park | known | 1 | — |
| gangnam-photo-01 | photo | space.river | partial | 0 | unusable_source_rows |
| gangnam-photo-01 | photo | space.facility | partial | 30 | projection_limit |
| gangnam-photo-01 | photo | environment.weather | unavailable | — | http_403 |
| gangnam-note-later | note | space.park | known | 1 | — |
| gangnam-note-later | note | space.river | partial | 0 | unusable_source_rows |
| gangnam-note-later | note | space.facility | partial | 30 | projection_limit |
| gangnam-note-later | note | environment.weather | unavailable | — | http_403 |
| gangnam-note-unlocated | note | space.park | not_requested | — | location_missing |
| gangnam-note-unlocated | note | space.river | not_requested | — | location_missing |
| gangnam-note-unlocated | note | space.facility | not_requested | — | location_missing |
| gangnam-note-unlocated | note | environment.weather | not_requested | — | location_missing |
| gangnam-note-legacy | note | space.park | known | 1 | — |
| gangnam-note-legacy | note | space.river | partial | 0 | unusable_source_rows |
| gangnam-note-legacy | note | space.facility | partial | 30 | projection_limit |
| gangnam-note-legacy | note | environment.weather | unavailable | — | http_403 |

원본 글·사진·행동 및 시각·좌표는 입력 그대로 보존한다.
공원 대표점·하천 시점·상가 등록점 근접은 실제 방문이나 내부 판정이 아니다.
성공한 빈 결과와 실패/부분 수집을 구별한다. 공원은 강남구 제공 자료만 조회한다.
날씨는 지정한 서울 108 관측소의 시간 자료이며 핀에서 직접 측정한 값이 아니다.
원본 API 응답은 private cache에 있고 이 출력에는 허용한 공급자 필드만 포함한다.
