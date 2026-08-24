# 백로그 — 갈래에 안 붙는 미결

갈래에 붙는 미결은 각 `explorations/*/*.md` 하단 체크리스트로.

## 팀에 요청/확인
- [ ] PostGIS 확장 (팀 PostgreSQL 인스턴스) — 로컬은 docker-compose로 검증 완료
- [ ] 아키텍처 그림에 산책 세션 API를 Agent Router 바깥으로 반영
- [ ] 반려견 프로필 조회 API/스키마 (`profile_version` 포함) — `contracts/dog-profile.md` 인터페이스 제안
- [ ] 보행체크 AI와의 경계: 산책이 수집한 GPS/속도 데이터를 넘겨주는지, 완전 분리인지
- [ ] 팀 레포 구조(모노/멀티) — 병원 에이전트를 팀 FastAPI에 넣을지, 이 레포가 별도 서비스인지

## 이 레포에서 정할 것
- [ ] **위치 프라이버시 정책** — 시작/종료 좌표뿐 아니라 시설 encounter 순서의 재식별,
      원본·파생 사실별 보관 기간, 동의·세션 삭제
- [x] 산책 세션 API·저장·`WalkFacts`·시설 occurrence 집계 구현
- [x] Android foreground service가 위치수집 생명주기 소유
- [ ] Android Room 영속 저장·위치 배치 업로드·process-death 복구 주기 (배터리 vs 유실)
- [ ] GPS 품질·어뷰징 검증 임계값 (accuracy, 속도, 점프, 가속도)
- [ ] 병원 **영업시간 데이터 출처** — 공공데이터에 없음. 수기·제휴 또는 parked `homepage-enrich.md`
- [ ] 검색 후처리로 후보가 빠질 때 반경 안의 다음 후보를 refill하는 방식
- [ ] Android 실기기 위치·지도·백그라운드 smoke test와 release 서버 설정
- [ ] PostGIS 통합 테스트를 포함한 CI
- [ ] 딥링크 스킴 이름 (`daengs://` 가안)

## 현재 코어에 필요한 키·환경
- [ ] NAVER Cloud Maps Dynamic/Static Map 키와 Android 패키지·웹 서비스 URL 등록
- [ ] 공공데이터포털 행안부 동물병원·동물약국 조회서비스 활용신청 및 운영키 등록

## parked 기능을 다시 채택할 때만
- [ ] 네이버 개발자센터 검색 API 앱 등록 (`community-search.md`)
- [ ] 카카오 REST 키 (`kakao-category.md`, 지오코딩)
- [ ] TMAP 키·요금 재확인 (`transport-snapshot.md` 도보)
- [ ] 자동차·대중교통 실측 provider 선정
- [ ] 이동 중 알림 빈도와 프로필 기반 권장 시간·거리 규칙 결정
