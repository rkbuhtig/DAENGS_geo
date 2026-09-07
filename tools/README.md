# 사람이 조작하는 검토 도구

공용 API는 `uv run uvicorn app.main:app --reload`로 실행한다.
검토 화면은 아래 입구에서 **도구를 명시적으로 선택**해 연다.
`DAENGS_DEV_CONSOLE=true`만으로 공용 API에 검토 화면이 추가되지 않는다.

## 선택 실행

Geo 저장소 루트에서 Python 3.12와 `uv sync`로 의존성을 준비한다.
기본 주소는 `127.0.0.1:8000`이며, 명령은 loopback에만 바인딩한다.
공용 API와 함께 실행하면 `--port 8001`처럼 포트를 나눈다.

```bash
uv run python -m tools.lab_server --tool walk-trace
uv run python -m tools.lab_server --tool cellophane --tool spatial-diary --port 8001
uv run python -m tools.lab_server --tool territory-season
uv run python -m tools.lab_server --tool place-ui
```

`--tool`을 반복하면 필요한 도구를 함께 연결한다. 선택이 없거나 이름이 틀리면 시작하지 않는다.
Python에서는 `create_app(enabled_tools=["walk-trace"])`로 같은 앱을 구성한다.
각 도구의 폴더가 라우트·검토 데이터·정적 파일을 함께 소유한다.
`lab_server.py`는 선택한 도구와 필요한 지도 API·요청별 사용량 처리만 연결한다.

| 선택 이름 | 기존 URL (선택한 서버 주소 기준) | 입력·실행 조건 |
|---|---|---|
| `walk-trace` | `/walk-trace-lab`, `/walk-trace-lab/example`, `/walk-trace-lab/run` | 합성 경로·GPS 관측 계산. 서버 파일·PostGIS 저장 없음. [계약·실행](../docs/explorations/walk/recording/simulator-core.md) |
| `cellophane` | `/cellophane`, `/cellophane-distribution`, `/continuous-hex-comparison` 및 각각 `/data` | CWD의 `cellophane.json`, `cellophane-distribution.json`, `continuous-hex-visualization.json`. 없는 파일은 404. 화면에서 파일을 직접 열 수도 있음 |
| `spatial-diary` | `/spatial-diary-lab`, `/spatial-diary-lab/data` | canonical Paint로 생성한 합성 UI fixture. DB·외부 캐시 없이 계산. 실험용 경로·Pin과 계산 출처를 기존 응답 그대로 전달 |
| `world-context` | `/world-context`, `/world-context/data/{name}` | CWD의 `latent.json`, `world_context.json`, `osm_world.json`만 제공. 합성 사건과 저장된 세계 자료를 비교하는 기존 도구 |
| `territory-sites` | `/dev/territory-sites`, `/dev/territory-sites/search` | 실제 PostGIS와 적재한 점령지 필요. [게임 입구](../docs/explorations/walk/game/README.md) |
| `territory-season` | `/territory-season-lab/`, 하위 `/api/seasons` | 합성 입력·로컬 SQLite. PostGIS·지도 키·공용 설정을 불러오지 않음 |
| `place-ui` | `/place-ui-lab/` 및 정적 에셋 | 저장된 공개 검색 응답 24개. PostGIS·지도 키·공용 설정을 불러오지 않음 |
| `place-intent` | `/place-intent-lab`, `/dev/place-intent/{search,refine,confirm,interact,observations}` | 실제 PostGIS, Gemini 설정·키, 사용량 정책. [공급자 조립](../docs/provider-assembly.md), [계획](../docs/explorations/facility/intent-planner.md) |
| `facility` | `/facility-map`, `/v2/places/search` | 실제 PostGIS의 Place 검색. [시설 검색](../docs/explorations/facility/README.md) |

지도 도구는 기존 `/map/client-config`와 `/map/static`을 함께 연결한다.
브라우저 지도·타일 로딩에는 기존 외부 지도 연결이 필요하며 Naver/OSM 선택과 폴백은 유지한다.
외부 호출의 `DAENGS_USAGE_POLICY`와 요청별 예산도 기존 Usage Gate를 그대로 사용한다.
도구를 선택해도 유료 모델이나 외부 수집을 시작할 때 필요한 설정을 대신하지 않는다.
공용 산책·일기·점령 API 전체를 검토 서버에 함께 마운트하지 않는다.

## 데이터 위치와 기존 도구

서버를 시작한 작업 디렉터리(CWD)를 유지하면 고정 JSON·SQLite 위치도 그대로다.
시즌 기본 DB는 기존 공용 앱에서 사용하던 `.local/territory-season.sqlite3`다.
다른 파일은 `--season-db .local/my-game.sqlite3`로 명시하며 선택한 기존 파일을 읽고 이어 쓴다.
`territory-season`을 선택하지 않으면 시즌 DB를 만들지 않는다.
코드·정적 에셋의 위치는 실행한 CWD와 무관하게 저장소 기준으로 찾는다.
시즌 화면의 진행 중 산책·재시도 정보는 기존 브라우저 localStorage 키를 유지한다.
이 정보까지 이어 쓰려면 기존과 같은 호스트·포트로 접속한다. 포트를 바꾸면 SQLite 기록은
같은 파일에서 읽을 수 있지만 브라우저 저장소는 별도 출처로 취급된다.

기존 독립 실행 명령도 유지한다. 아래 도구를 통합 서버의 필수 구성으로 만들지 않는다.

| 도구 | 실행·저장 조건 |
|---|---|
| [시즌 게임](../scripts/spikes/territory_season/README.md) | `uv run python -m scripts.spikes.territory_season.server`; 기존 `--db`·포트와 루트 URL 유지 |
| [산책 기록·환경 lab](../scripts/spikes/walk_record_lab/README.md) | 기존 `server --cache-dir ...` 사용. 외부 캐시·선택적 수집 조건 유지 |
| [시설 검토](facility-review/README.md) | 기존 Python·JS·브라우저 실행 및 실제 서버/저장 표본 모드 유지 |
| [일기 LLM 실험](../scripts/spikes/diary_storyboard/README.md) | 기존 CLI와 외부 캐시·검토본·별도 생성 요청 유지 |

## 소유 위치와 검증

```bash
uv run pytest -q tests/tools tests/spikes/walk_record_lab
uv run pytest -q tests/test_repository_imports.py tests/test_import_direction.py
```

`tests/tools/`는 기본 pytest 수집과 CI에 포함된다. 기존 도메인 테스트는 각 소유 위치에서
같이 실행하며, `facility-review`의 별도 검사 명령은 해당 README를 따른다.
[결정 #86](../docs/decisions/2026-09-07-repository-execution-boundaries.md)의
`app.main → scripts.sim.walk.lab` 임시 예외는 3차에서 제거했다.

| 도구 소유 위치 | 검토 구현·정적 파일 | 남겨 둔 공용·실험 구현 |
|---|---|---|
| `walk_trace/` | `lab.py`, `record_server.py`, `static/` | `scripts/sim/walk` 생성기, `scripts/spikes/walk_record_lab` 실험·캐시·선택 |
| `cellophane/` | `lab.py`, `static/` | `app/features/territory` 계산, `scripts/spikes/territory_paint` 실험 |
| `spatial_diary/` | `lab.py`, `fixture.py`, `static/` | `app/features/spatial_diary` 공용 계약·서비스 |
| `world_context/` | `lab.py`, `static/` | 기존 세계 자료 생성기·고정 CWD JSON |
| `territory_game/` | `sites_lab.py`, `season_lab.py`, `local_store.py`, `local_schema.sql`, `static/` | `app/features/territory_game` 정책·계약·PostgreSQL 저장 |
| `place_ui/` | `lab.py`, `static/` (표본 포함) | `app/place` 검색 구현 |
| `place_intent/` | `lab.py`, `static/` | `app/discovery/place_intent` planner·lens·관측 저장 |
| `facility/` | `lab.py`, `static/` | `app/api/places_v2.py`, `app/place` 검색 |

`tests/tools/<도구>/`는 이전 화면·HTTP·로컬 저장 테스트를 소유한다.
산책 기록 실험의 계산·HTTP 통합 검증은 `tests/spikes/walk_record_lab/`에 둔다.
`tests/tools/test_tool_imports.py`는 Python 도구를 발견해 import하며, 이동한 산책 lab의
기존 scripts import 검사도 여기서 이어 간다. 별도 `facility-review` 검사는 위 안내를 따른다.
