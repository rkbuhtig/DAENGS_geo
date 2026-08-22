# DAENGS_geo

댕스(DAENGS) 반려견 케어 서비스의 **지오 백엔드 + Android 기준 클라이언트**.
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
│   └── walk/      수집만 — WalkFacts (contracts/walk-record.md). 판정·서술 없음, 테스트로 고정
├── api/         GET /places/search · GET /map/static
├── usage/       실제 외부 호출 Gate — 기본 거부, 제한형 dev 정책, 요청/시간당 사용량
└── core/        config · db
android/         Kotlin/Compose 단일 모듈 — 위치 → 검색 → NAVER 지도 → actions/전화 수직 절단면
```

**LLM은 `utterance`가 있을 때만**, 그것도 "말 → 툴 호출" 번역 한 겹. 병원 정보 생성 안 함. UI 필터(`edits`)와 자연어는 같은 툴로 수렴.

진짜 vs 가짜: PostGIS 검색·영업시간·태깅·상태 편집·diff·스냅샷 조립·advice 규칙은 진짜 /
LLM·경로·커뮤니티 검색·프로필은 기본 가짜 또는 미설정. 지도 표면은 키를 넣으면 NAVER
Dynamic Map + Static Map, 없으면 `/dev`에서만 OSM으로 내려간다.

## 실행

```bash
cp .env.example .env
docker compose up -d            # PostGIS 16-3.4, migrations/ 자동 적용
docker compose exec -T db psql -U daengs -d daengs < migrations/dev_seed.sql   # 개발용 시드
uv sync
uv run uvicorn app.main:app --reload
uv run pytest
```

Android 앱은 [`android/README.md`](android/README.md)를 따른다. 백엔드와 같은 레포에 있지만
Gradle 프로젝트는 `android/` 아래에 독립되어 있어 Python 실행·테스트와 섞이지 않는다.

### 실제 외부 호출 사용량 Gate

NAVER Static Map, TMAP 실측 경로, OpenAI 자연어 파싱은 모두 같은 Usage Gate를 통과한다.
코드 기본값 `DAENGS_USAGE_POLICY=deny-all`에서는 실제 provider를 호출하지 않는다. 로컬에서
실제 키를 검증할 때만 `dev`를 명시한다. `dev_console`과는 독립된 설정이다.

| operation | dev 요청당 | dev 시간당 | 거부 시 |
|---|---:|---:|---|
| Static Map | 1 | 100 | HTTP 403/429 |
| 실측 경로 | 4 | 60 | `estimate`, `status_reason=usage_denied` |
| OpenAI 파싱 | 1 | 30 | HTTP 403/429 |

dev 누적량은 프로세스 메모리에 있어 재시작하면 초기화되고 여러 worker가 공유하지 않는다.
팀 서비스에 합칠 때 `UsagePolicy`와 `UsageLedger` 조립만 인증 컨텍스트·공유 저장소 구현으로
교체한다. provider와 실행 Gate는 그대로 둔다.

### 실제 병원·약국 데이터 동기화

행정안전부 공공데이터포털의 전국 동물병원·동물약국 인허가 데이터를 `place`에 적재한다.
공공 API는 사용자 검색 시 호출하지 않고 배치에서만 호출한다. 좌표(EPSG:5174)는 적재 시
PostGIS에서 WGS84(EPSG:4326)로 변환하며, 검색 후 선택한 목적지만 기존 `/journey`가 TMAP에 넘긴다.

기존 `pgdata` 볼륨은 Docker 초기화 SQL을 다시 실행하지 않으므로 마이그레이션을 한 번 적용한다.

```bash
docker compose exec -T db psql -U daengs -d daengs \
  -f /docker-entrypoint-initdb.d/003_mois_ingest.sql
```

```bash
# data.go.kr에서 받은 일반(Decoding) 인증키
DAENGS_DATA_GO_KR_SERVICE_KEY=... uv run python -m app.ingest full

# 이후 매일. 마지막 원천 갱신시점에서 3일 겹쳐 변경분을 다시 받는다.
DAENGS_DATA_GO_KR_SERVICE_KEY=... uv run python -m app.ingest incremental

# 한 종류만 동기화
uv run python -m app.ingest full --kind hospital
uv run python -m app.ingest full --kind pharmacy
```

- 원천: [동물병원 조회서비스](https://www.data.go.kr/data/15154952/openapi.do),
  [동물약국 조회서비스](https://www.data.go.kr/data/15155272/openapi.do)
- `SALS_STTS_CD=01`만 `active=true`; 휴업·폐업·취소·삭제·기타는 검색에서 제외한다.
- 영업상태는 인허가 상태이지 현재 영업시간이 아니다. 이 API는 `hours`, 야간·24시간 진료를 제공하지 않는다.
- 좌표가 없거나 변환 후 대한민국 범위를 벗어난 신규 레코드는 저장하지 않는다. 기존 레코드는 좌표가
  사라져도 폐업 등 상태 변경을 반영한다.

**검증 콘솔**: `http://127.0.0.1:8000/dev` (`DAENGS_DEV_CONSOLE=true` 일 때만 — `.env.example` 에 켜져 있다. 코드 기본값은 닫힘) — 페르소나·출발지(지도 클릭)·필터 칩·자연어 입력, 카드 클릭하면 도보 폴리라인 + 반려견 관심 지점(spots) + 따라가기 딥링크. NAVER Web 서비스 URL은 포트 없이 `http://127.0.0.1`을 등록한다.

현재 공급자 선택·폴백·교체 실험 방법은 [`docs/provider-assembly.md`](docs/provider-assembly.md)에
한 표로 관리한다. 현재 실제 조립 범위는 NAVER Dynamic Map + Static Map이고, 검색은 PostGIS,
지오코딩과 실제 경로 공급자는 보류다.

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
