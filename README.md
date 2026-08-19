# DAENGS_geo

댕스(DAENGS) 반려견 케어 서비스의 **지오 백엔드**.
두 기능이 하나의 위치 인프라(PostGIS 반경 검색 · 좌표 인덱싱 · 영업시간 판정)를 공유한다.

| 기능 | 성격 | 진입 |
|---|---|---|
| **병원/약국 찾기** | 요청-응답 (검색 + 자연어 파싱) | 챗봇 대화 / 일반 메뉴 |
| **산책 세션** | GPS 스트림 수신 + 상태 유지 + 트리거 서술 | Android 앱 (백그라운드 GPS) |

## 상태

**구상 단계.** 코드 없음. `docs/` 에 확정된 설계 결정만 기록.

## 확정 사항 (2026-08-19)

- 백엔드: **FastAPI / Python**, DB: **PostgreSQL + PostGIS** (팀 pgvector와 동거)
- 클라이언트: 웹 메인 + **Android(Kotlin) 전용** 앱. iOS 없음
- 산책은 백그라운드 위치가 필요하므로 네이티브 앱에서만. 병원/약국은 웹·앱 양쪽
- 반려견 프로필은 이 레포가 소유하지 않는다 → 외부 계약으로 소비 (`docs/02-dog-profile-contract.md`)
- 산책 게임에 판타지 세계관 없음. 에이전트 = 프로필 기반 **개의 목소리**, 진행도 = 현실 기반
- 판정·보상은 코드가 결정, LLM은 서술과 자연어 파싱만

## 문서

1. [컨셉](docs/01-concept.md)
2. [반려견 프로필 계약 + 가상 페르소나](docs/02-dog-profile-contract.md)
3. [병원/약국 찾기](docs/03-hospital-search.md)
4. [산책 세션 엔진](docs/04-walk-session.md)
5. [아키텍처 결정 기록](docs/05-decisions.md)
6. [미결 사항](docs/06-open-questions.md)
