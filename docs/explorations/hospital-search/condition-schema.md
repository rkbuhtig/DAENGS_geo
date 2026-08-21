---
status: exploring
---
# 조건 스키마 — 필터 / 정렬 / 표시를 나눠서

| 축 | 조건 | 출처 | 역할 | 지금 |
|---|---|---|---|---|
| 위치 | origin, radius_m | 사용자/프로필 | 필터 | ✅ |
| | mode(walk/car/transit), max_minutes | 사용자. transit은 size_class=small만 노출 | **정렬 기준** | route 어댑터 후 |
| 시간 | open_now, open_at | hours | 필터. **미상은 제외 안 함** | ✅ |
| | night, is_24h, emergency | 이름 태그/수기 | 필터 | 컬럼 |
| 종류 | dog_ok | 카테고리 (`고양이 전문` 배제) | **전제 필터, 비노출** | — |
| | specialty | 카카오 카테고리 + 커뮤니티 근거 | 필터(요청 시) / 부스트 | — |
| | large_dog_ok | 수기 | 필터 | — |
| 규모 | 면적·종사자수 | 인허가 | **표시만** | 적재 후 |
| | has_inpatient / night_staff / ct_mri / parking | 수기·홈페이지 | 필터(요청 시) | — |
| 평가 | 커뮤니티 evidence | 네이버 검색 API | **부스트 + 표시** | 탐색 중 |
| | 제공사 리뷰 | 링크아웃 | 표시 | — |
| | min_rating | — | **지원 안 함** | — |
| 개인화 | visited_ids | 이력 | 부스트/제외 | — |
| | home, size_class, health_flags | 프로필 | 기본값·제안만 | — |
| 세션 | exclude_ids, pin_ids, sort, history | 대화 | 편집 | — |

원칙: 데이터 없는 병원을 **결과에서 빼지 않는다.** 미상은 미상으로 표시.

## 요청 계약 v2

클라이언트가 왕복시키는 `EditableState`에는 `state_version: 2`가 붙는다. 서버는
버전 없는 v1 state의 `target.night`, `target.emergency`, `target.at`을 각각
`night_service`, `emergency_service`, `time_intent(kind=service_at)`으로 이행한다.
옛 `set_time(open_now, night, emergency)` 편집도 입력 호환용으로만 받으며 새 툴
목록에는 노출하지 않는다. 알 수 없는 버전·필드·툴·인자는 조용히 버리지 않고 422다.

- 위도 `-90..90`, 경도 `-180..180`
- 반경 `100..20,000m`, 결과 `1..100`
- 편집 20개, 화면 ID 100개, undo history 10개
- 새 요청의 `origin`은 왕복된 state 좌표보다 우선하고, 그 뒤 명시적 `set_origin` 편집이 우선한다
