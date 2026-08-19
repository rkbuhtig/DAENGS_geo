# DAENGS_geo

댕스(DAENGS) 반려견 케어 서비스의 **지오 백엔드**.
두 기능이 하나의 위치 인프라(PostGIS 반경 검색 · 좌표 인덱싱 · 영업시간 판정)를 공유한다.

| 기능 | 성격 | 진입 |
|---|---|---|
| **병원/약국 찾기** | 요청-응답 (검색 + 자연어 파싱) | 챗봇 대화 / 일반 메뉴 |
| **산책 세션** | GPS 스트림 수신 + 상태 유지 + 트리거 서술 | Android 앱 (백그라운드 GPS) |

## 상태

**공통 지오 레이어 1차 완료** (2026-08-19). 병원/약국 · 산책이 공유하는 부분만 깔았다.

- `app/providers/` — 지도 제공사 어댑터 (`MapProvider` 3메서드: 정적지도 URL / 지오코딩 / 역지오코딩). 카카오·네이버 구현체, 설정으로 메서드별 선택
- `app/geo/` — `place` 모델(PostGIS), 영업시간 판정(`hours.py`, 순수함수), 반경 검색(`search.py`)
- `app/api/` — `GET /places/search` (메뉴 진입용), `GET /map/static` (정적 지도 프록시)
- 아직 없음: 챗봇 `parse()`, 공공데이터 적재, 산책 세션

## 실행

```bash
cp .env.example .env
docker compose up -d            # PostGIS 16-3.4, migrations/ 자동 적용
docker compose exec -T db psql -U daengs -d daengs < migrations/dev_seed.sql   # 개발용 시드
uv sync
uv run uvicorn app.main:app --reload
uv run pytest
```

```
GET /places/search?lat=37.4979&lng=127.0276&kind=hospital&night=true&open_now=true
→ { params, results[{id,name,lat,lng,distance_m,open_now,hours_today,...}], map{preview_url,deeplink,web_url} }
```

## 확정 사항 (2026-08-19)

- 백엔드: **FastAPI / Python**, DB: **PostgreSQL + PostGIS** (팀 pgvector와 동거)
- 클라이언트: 웹 메인 + **Android(Kotlin) 전용** 앱. iOS 없음
- 산책은 백그라운드 위치가 필요하므로 네이티브 앱에서만. 병원/약국은 웹·앱 양쪽
- 반려견 프로필은 이 레포가 소유하지 않는다 → 외부 계약으로 소비 (`docs/contracts/dog-profile.md`)
- 산책 게임에 판타지 세계관 없음. 에이전트 = 프로필 기반 **개의 목소리**, 진행도 = 현실 기반
- 판정·보상은 코드가 결정, LLM은 서술과 자연어 파싱만

## 문서

[docs/README.md](docs/README.md) 가 지도. 확정(`decisions/`) · 계약(`contracts/`) · 갈래(`explorations/`) · 조사(`research/`)로 나뉘고, 갈래는 status(exploring/adopted/parked/rejected)로 상태를 표시한다.
