# 테스트 소유권

## 폴더 = 소유권

한 폴더의 테스트들이 **대체로 같은 이유로 깨져야** 한다. 파일을 열기 전에 "어디를
봐야 하나"가 답해지는 것이 이 구조의 목적이다.

```
activity_statistics/ 산책·점령 세션 연결·순수 통계·PostgreSQL 재처리
api/            HTTP 표면 — 입력 검증, 상태코드, 응답에 나가면 안 되는 값
context_plane/  typed Atom·Facet·Lens, registry와 기존 기능 adapter
core/           설정·DB·스키마 리비전 판별 같은 공통 런타임 경계
discovery/      intent observation·planner·lens·refine·dev 관측 경로
geo/            좌표·시간·태그·반려동물 조건·PostGIS 검색 primitive
ingest/         공공데이터 원천 정규화·적재·연결·제약 사실
integration/    여러 소유 경계를 실제 DB·API로 관통하는 검증
journey/        이동 snapshot·advice·handoff·경로 선택
place/          canonical Place 계약·resolver·검색·제약 projection
profile/        외부 Dog/Owner profile 계약과 테스트용 source
providers/      외부 지도·경로 제공사 경계와 진실성 계약
sim/            장기 산책·Cellophane 통계 시뮬레이션
spikes/         갈래별 실험 실행·상태·근거 계약 (diary_storyboard/ 등)
spatial_diary/  Capsule 소비·Offer·Attestation·Pin·Journal·Snapshot
territory/      Cellophane·Field·조건별 View·Memory Place
territory_game/ 점령 정책·트랜잭션·PostgreSQL·순수 시즌 게임
tools/          도구별 화면·HTTP·로컬 저장, 선택 실행 경계
usage/          실제 외부 호출 Gate — 허용·요청당 한도·누적 사용량
walk/           산책 세션·fix·WalkFacts·Capsule 봉인, 수집 계약
```

`fixtures/`는 녹화된 외부 출력 같은 재현 자료만 둔다. 테스트 소유권은 위 도메인 폴더가 가진다.

`conftest.py` 는 루트에 하나다. **만드는 방법만 공유하고 무엇을 만들지는 각 테스트가
소유한다** — 그 경계의 이유는 `conftest.py` 첫 문단에 있다. 새 범용 fixture 생성기를 도메인별 `fixtures.py`로
늘리지 않는다. 기존 `activity_statistics/fixtures.py`처럼 특정 통계 시나리오의 입력을 소유하는
파일은 공용 pytest fixture 등록과 구분한다.

루트에 남은 `test_storyboard_sources.py`·`test_storyboard_regions.py`는 기존 장면 실험 검사다.
새 장면 실험 검사는 소유 폴더에 배치한다. 기존 파일의 위치만으로 저장소 전체 검사라고 판단하지 않는다.

## 규칙

**새 회귀 테스트는 버그가 난 기능의 소유 폴더에 둔다.** "어디 둘지 모르겠어서 공용
파일에" 는 금지다. 그렇게 만들어진 것이 `test_request_contract.py` 였고, 이름은 하나인데
안에 서로 다른 여섯 계약이 있어서 무엇을 고칠 때 봐야 하는지 알 수 없었다.

**`parked/` 폴더는 만들지 않는다.** 제품 기능이 보류·탐색 중인 것과 코드가 죽은 것은 다르다.
예를 들어 자연어 intent lab은 dev-only 탐색 표면이지만 observation·planner·lens의 실행 계약은
`discovery/`가 검증한다. `refine/tools`도 UI 필터(`edits`)의 실행기라 같은 검색 경로 위에
있다. 틀린 라벨은 없는 라벨보다 나쁘다.

## Decision 링크 = 근거

정책·제품 결정에서 직접 파생된 테스트에만 붙인다. 전부에 달 필요 없다.

```python
def test_map_pan_is_undoable_but_a_gps_refresh_is_not():
    """
    Contract: 지도 팬은 명시적 편집이라 되돌릴 수 있고, GPS 갱신은 기기 사실이라
              history 에 안 들어간다.
    Decision: #37, #46
    """
```

**번호만 쓰지 말고 내용을 같이 적는다.** 번호가 틀리면 다음 사람이 엉뚱한 결정을 근거로
삼는다. 실재하지 않는 번호는 `test_decision_refs.py` 가 막는다.

이 링크는 테스트가 깨졌을 때 답을 갈라준다.

```
결정이 아직 유효한가?
├─ YES → production 회귀다. 코드를 고친다
└─ NO  → 계약이 바뀐 것이다. 테스트를 바꾸거나 지운다
```

**결정 문서는 테스트의 근거가 될 수 있지만 테스트 분류가 되어서는 안 된다.** 하나의
결정이 여러 도메인에 걸치고, 하나의 테스트가 두 결정의 결과일 수 있다. 소유권은 폴더가
1:1 로, 근거는 링크가 N:M 으로 나타낸다. `decision-37/` 같은 폴더를 만들지 마라.

## 저장소 구조 검사와 이동 검증

[결정 #86](../docs/decisions/2026-09-07-repository-execution-boundaries.md)은
공용 구현과 검토 도구·실험의 소유권을 구분한다.

- `test_import_direction.py`: 결정 #67의 app 내부 계층·계약·순환 검사.
- `test_repository_imports.py`: app → tools/scripts/tests의 새 의존을 차단한다.
  3차에서 `app.main → scripts.sim.walk.lab`을 제거해 현재 예외는 없다.
  임시 소스에서 금지 import·누락 파일을 넣어 검사 실패를 확인한다.
- `tools/test_lab_server.py`: 공용 앱의 도구 미로딩, 선택 실행, 고정 fixture, 시즌 저장·복원,
  요청별 사용량 경계. [실행 안내](../tools/README.md).
- 일기 실험 세 파일은 `spikes/diary_storyboard/`가 소유한다. fixture 생성 방식은
  기존 루트 `conftest.py`를 사용하며 도메인별 공용 fixture 파일을 늘리지 않는다.

```bash
uv run pytest tests/test_import_direction.py tests/test_repository_imports.py tests/spikes/diary_storyboard -q
uv run pytest --collect-only -q
```

파일 이동 PR은 이전·이후 수집 nodeid를 경로 대응표로 비교한다. 항목 수만 같다고
누락이 없다고 판단하지 않는다. 날짜가 붙은 연구 문서에는 당시의 옛 명령이 남을 수 있으며,
현재 일기 실험 명령은 [실험 README](../scripts/spikes/diary_storyboard/README.md)를 따른다.

pytest 기본 범위는 `tests/`다. `tools/facility-review/test_serve.py`는 별도 실행해야 하고
먼저 npm 의존성이 필요하다. Python·JS·브라우저 명령과 선택적인 DEV 표본 환경은
[도구 README](../tools/facility-review/README.md)에 있다. 기본 CI가 이 별도 검사를
실행한다고 읽지 않는다.

## 실행 환경과 skip 확인

Geo 루트에서 Python 3.12와 `uv sync --frozen`으로 준비한다.

```bash
uv run ruff check .
uv run pytest -q -rs
```

| 검사 | 실행 조건 | 조건이 없을 때 |
|---|---|---|
| 공용 DB fixture를 쓰는 검사 | `DAENGS_DATABASE_URL`의 PostGIS와 Alembic 적용 | 연결 실패 시 `skip` |
| 점령 정책·세션 통계 PostgreSQL 검사 | 마이그레이션된 폐기 가능한 테스트 DB를 `DAENGS_POLICY_TEST_URL`로 명시 | 미설정 시 `skip`; 설정 후 연결·스키마 오류는 실패 |
| `test_storyboard_regions.py` | 선택 의존성 `shapely`, `pyproj` | 모듈 수집 시 `skip` |
| `tools/facility-review` Python·JS·브라우저 | npm 및 검사별 실행 조건 | 기본 pytest·CI 범위 밖; [별도 안내](../tools/facility-review/README.md) |

DB 준비는 [빠른 실행](../README.md#빠른-실행)과 [Alembic 안내](../alembic/README.md)를 따른다.
정책·통계 검사는 공용 DB URL로 자동 폴백하지 않는다. 로컬 테스트 DB를 명시하는 예시는 다음과 같다.

```bash
# Bash. 준비한 테스트 DB의 URL로 지정한다.
export DAENGS_POLICY_TEST_URL=postgresql+asyncpg://daengs:daengs@localhost:5432/daengs
uv run pytest tests/territory_game/test_policy_postgres.py tests/activity_statistics/test_postgres.py -q -rs
```

PowerShell은 첫 줄 대신 `$env:DAENGS_POLICY_TEST_URL = 'postgresql+asyncpg://daengs:daengs@localhost:5432/daengs'`를 쓴다.
지역 geometry 검사는 외부 API·개인 SGIS 파일 없이 실행한다.

```bash
uv run --with shapely --with pyproj pytest tests/test_storyboard_regions.py -q -rs
```

[CI](../.github/workflows/ci.yml)는 두 DB URL을 설정하고 Alembic 적용 후 pytest를 실행한다.
로컬과 CI 모두 통과 수뿐 아니라 `-rs`의 skip 사유를 확인해야 한다. CI 기본 의존성에는
위 geometry 패키지가 없고, 브라우저·실기기 검증도 별도이므로 전체 검증 완료로 해석하지 않는다.
