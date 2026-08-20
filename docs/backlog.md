# 백로그 — 갈래에 안 붙는 미결

갈래에 붙는 미결은 각 `explorations/*/*.md` 하단 체크리스트로.

## 팀에 요청/확인
- [ ] PostGIS 확장 (팀 PostgreSQL 인스턴스) — 로컬은 docker-compose로 검증 완료
- [ ] 아키텍처 그림에 산책 세션 API를 Agent Router 바깥으로 반영
- [ ] 반려견 프로필 조회 API/스키마 (`profile_version` 포함) — `contracts/dog-profile.md` 인터페이스 제안
- [ ] 보행체크 AI와의 경계: 산책이 수집한 GPS/속도 데이터를 넘겨주는지, 완전 분리인지
- [ ] 팀 레포 구조(모노/멀티) — 병원 에이전트를 팀 FastAPI에 넣을지, 이 레포가 별도 서비스인지

## 이 레포에서 정할 것
- [ ] 병원 **영업시간 데이터 출처** (공공데이터에 없음. 최대 작업량) — 후보: `homepage-enrich.md`(parked), 수기, 제휴
- [ ] 위치 배치 업로드 주기 (앱 팀과 합의, 배터리 vs 반응성)
- [ ] 이동 중 알림 빈도 상한 값 (세션당 N회, 간격 M분)
- [ ] 위치 프라이버시 정책 (시작/종료 좌표 절삭, 보관 기간)
- [ ] 어뷰징 검증 임계값 (속도/가속도)
- [ ] 프로필 함수 구체값: 나이·체중·brachy·flags·기온 → 권장 시간/거리
- [ ] 지도 제공사 확정 (팀 클라이언트 SDK 결정 따름) — `explorations/map-provider/`
- [ ] 딥링크 스킴 이름 (`daengs://` 가안)


## 키 발급 (사용자)
- [ ] 네이버 개발자센터 검색 API 앱 등록 (`community-search.md`)
- [ ] 카카오 REST 키 (`kakao-category.md`, 지오코딩)
- [ ] TMAP(SK오픈API) 키 + 요금 확인 (`transport-snapshot.md` 도보)
- [ ] 네이버 클라우드 Maps 또는 카카오모빌리티 키 (자동차)
- [ ] 공공데이터포털 행안부 동물병원·동물약국 조회서비스 활용신청 및 운영키 등록
