# DAENGS_geo

댕스(DAENGS) 반려견 케어 서비스의 **지오 백엔드**.
두 기능이 하나의 위치 인프라(PostGIS 반경 검색 · 좌표 인덱싱 · 영업시간 판정)를 공유한다.

| 기능 | 성격 | 진입 |
|---|---|---|
| **병원/약국 찾기** | 요청-응답 (검색 + 자연어 파싱) | 챗봇 대화 / 일반 메뉴 |
| **산책 세션** | GPS 스트림 수신 + 상태 유지 + 트리거 서술 | Android 앱 (백그라운드 GPS) |

## 상태

**워킹 스켈레톤 동작** (2026-08-19). 키 0개로 메뉴/딥링크 진입 → 재조정(UI·자연어) → 검색 → 교통 스냅샷 → 근거 부착까지 끝까지 돈다. 외부 것은 전부 결정론 가짜, 인터페이스는 진짜.

```
app/
├── geo/         search(PostGIS) · hours · tagging · polyline                       공용
├── journey/     engine(route+캐시) · advice(개 계수·옵션 비교) · spots · handoff  공용 ← POST /journey
├── providers/   MapProvider 4메서드 — kakao/naver/tmap/fake/null, 모드별 선택      공용
├── profile/     Dog/OwnerProfile 계약 + 개 8마리·견주 5명 페르소나                 공용
├── refine/      검색 상태 편집기 — state(target/journey/view) · tools · nl · diff
├── enrich/      community(쿼리 재작성→검색→병원명 매칭→evidence, Fake 시드)
├── features/
│   ├── hospital/  POST /hospital/search (편집+검색, transport=estimate만)
│   ├── pharmacy/  GET /pharmacy/search (얇음, companion 기본 none)
│   └── walk/      사용자 담당
├── api/         GET /places/search · GET /map/static
└── core/        config · db
```

**LLM은 `utterance`가 있을 때만**, 그것도 "말 → 툴 호출" 번역 한 겹. 병원 정보 생성 안 함. UI 필터(`edits`)와 자연어는 같은 툴로 수렴.

진짜 vs 가짜: PostGIS 검색·영업시간·태깅·상태 편집·diff·스냅샷 조립·advice 규칙은 진짜 / LLM·경로·커뮤니티 검색·프로필·정적지도는 가짜(설정 한 줄로 교체).

## 실행

```bash
cp .env.example .env
docker compose up -d            # PostGIS 16-3.4, migrations/ 자동 적용
docker compose exec -T db psql -U daengs -d daengs < migrations/dev_seed.sql   # 개발용 시드
uv sync
uv run uvicorn app.main:app --reload
uv run pytest
```

**검증 콘솔**: `http://localhost:8000/dev` — 페르소나·출발지(지도 클릭)·필터 칩·자연어 입력, 카드 클릭하면 도보 폴리라인 + 반려견 관심 지점(spots) + 따라가기 딥링크.

```
POST /hospital/search
{ "dog_id":"halmae", "origin":[37.4979,127.0276] }                                   ← 메뉴 진입(초안)
{ "dog_id":"halmae", "state":{...}, "utterance":"눈이 뿌옇고 걸어서 갈 데", "shown_ids":[..] }  ← 자연어/음성
{ "dog_id":"halmae", "state":{...}, "edits":[{"tool":"set_walk_max","args":{"minutes":15}}] }  ← 필터 UI
{ "dog_id":"dubu",   "state":{"lat":..,"lng":..,"night":true,"open_now":true} }         ← 챗봇 카드 딥링크
→ { state, results[{..., tags, transport{walk{min,m,facilities,advice,why}, car{taxi_fare}, transit}, evidence[]}],
    map{deeplink,web_url}, changes[], applied[], question?, reply }
```
시나리오 드라이버 예시는 커밋 메시지·`docs/research/2026-08-19-skeleton-run.md` 참고.

## 확정 사항 (2026-08-19)

- 백엔드: **FastAPI / Python**, DB: **PostgreSQL + PostGIS** (팀 pgvector와 동거)
- 클라이언트: 웹 메인 + **Android(Kotlin) 전용** 앱. iOS 없음
- 산책은 백그라운드 위치가 필요하므로 네이티브 앱에서만. 병원/약국은 웹·앱 양쪽
- 반려견 프로필은 이 레포가 소유하지 않는다 → 외부 계약으로 소비 (`docs/contracts/dog-profile.md`)
- 산책 게임에 판타지 세계관 없음. 에이전트 = 프로필 기반 **개의 목소리**, 진행도 = 현실 기반
- 판정·보상은 코드가 결정, LLM은 서술과 자연어 파싱만

## 문서

[docs/README.md](docs/README.md) 가 지도. 확정(`decisions/`) · 계약(`contracts/`) · 갈래(`explorations/`) · 조사(`research/`)로 나뉘고, 갈래는 status(exploring/adopted/parked/rejected)로 상태를 표시한다.
