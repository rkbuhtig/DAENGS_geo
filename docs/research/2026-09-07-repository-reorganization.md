# 저장소 구조 정리 0~6차 결과

2026-09-07 UTC. 이 기록은 디렉터리·실행 경계를 정리한 결과다. 운영 채택이나 제품
검증 완료를 선언하지 않는다. 0차 기준은 `0cb73776ad9df8d6ba04a769ff9fdbd7fe4a6894`,
6차 착수 main은 `620861da5e554f978e65bda3ce8f31c290c7108b`다.

## 변경과 현재 입구

| 단계 | 결과 |
|---|---|
| 0차 | 변경 전 테스트 nodeid·결과·HTTP·import·저장 경로 기준선 확보 |
| [1차 #251](https://github.com/rkbuhtig/DAENGS_geo/pull/251) | 저장소 간 import 검사와 일기 실험 테스트 분류 |
| [2차 #252](https://github.com/rkbuhtig/DAENGS_geo/pull/252) | walk 문서를 recording/spatial/diary/game/statistics로 분류, 일기 기획 통합 |
| [3차 #253](https://github.com/rkbuhtig/DAENGS_geo/pull/253) | 공용 API와 선택형 검토 서버의 실행 입구 분리 |
| [4차 #254](https://github.com/rkbuhtig/DAENGS_geo/pull/254) | 검토 HTTP·에셋·fixture·시즌 SQLite를 tools 소유로 이전 |
| [5차 #255](https://github.com/rkbuhtig/DAENGS_geo/pull/255) | 공용 게임을 features/territory_game으로 독립 |
| 6차 | seed·스키마 안내·현재 구조도·실험 목록·승격 경로 추적 정리 및 0차 대조 |

현재 구조는 [루트 지도](../../README.md#저장소-지도), 실행은
[tools](../../tools/README.md)·[scripts](../../scripts/README.md), 문서는
[walk 입구](../explorations/walk/README.md), 테스트는 [소유권 안내](../../tests/README.md)를 따른다.
규칙과 단계별 이행은 [결정 #86](../decisions/2026-09-07-repository-execution-boundaries.md)에 있다.

`app`에서 tools/scripts/tests로 향하는 예외는 없다. 기존 app 내부 계층·계약·형제 DAG
검사도 유지한다. 게임 정책·배점·SQL·공용 API 의미와 기존 Alembic 리비전은 유지했다.

## 의도적으로 바꾼 실행 방법

공용 API는 `uv run uvicorn app.main:app --reload`, 검토 화면은
`uv run python -m tools.lab_server --tool <이름>`으로 연다. 이전 dev_console 플래그만으로
공용 API에 화면이 붙지 않는다. 검토 URL 경로는 새 서버에서 유지한다.

| 유지한 경계 | 이유 |
|---|---|
| 고정 JSON의 CWD 파일명 | 기존 생성 명령과 저장된 결과를 같은 위치에서 찾음 |
| 시즌 기본 `.local/territory-season.sqlite3`와 명시 DB 경로 | 기존 시즌·명령 재시도·이력을 이어 읽음 |
| 브라우저 localStorage 키·호스트·포트 안내 | 파일 위치 이동과 브라우저 origin 변경을 구별 |
| 산책 기록·시즌 독립 CLI | 기존 실행 문서의 입구. 구현은 tools가 소유 |
| dev_console 호환 설정 | 이전 환경을 읽는 필드로 유지하며 도구 연결 기능은 없음 |
| export_copy의 명시적 legacy 실행 | 현재 승격 명령으로 쓰지 않는 과거 재현 입구 |

wheel은 기존처럼 app만 포함한다. tools·scripts는 저장소 체크아웃에서 실행한다.
새 임시 import 예외나 옛 app 패키지의 재수출 어댑터를 추가하지 않았다.

`migrations/dev_seed.sql`은 [seeds/dev_seed.sql](../../seeds/dev_seed.sql)로 바이트 그대로
옮겼다. 스키마 수명·옛 SQL 안내는 [alembic/README.md](../../alembic/README.md),
수동 seed 실행은 [seeds/README.md](../../seeds/README.md)에 있다. DB에 seed를 실제
적재하는 검증은 로컬 DB 부재로 하지 않았다.

## 0차 대비 검증

[기계가 읽을 수 있는 대조 결과](2026-09-07-repository-reorganization-checks.json)에
추가 nodeid와 실행 입구 검사 6개의 이름 대응을 기록했다.

| 항목 | 0차 | 6차 | 대조 |
|---|---|---|---|
| 기본 수집 item | 1,481 | 1,523 | 기존 item 모두 대응, 42개 추가 |
| 기존 item 결과 | 1,353 통과·128 skip | 같은 1,481개의 결과 동일 | 신규 실패·skip 없음, skip 사유 동일 |
| HTTP probe | 공용 13·개발 38·독립 15 | 66개 재실행 | 상태·body SHA-256·길이·기록된 응답 헤더 동일 |
| 공용 OpenAPI | 공용 모드 계약 | 동일 | 검토 API는 선택 서버로 이전 |
| 별도 시설 검사 | Python 3·JS 8 | Python 3·JS 8 통과 | 기본 pytest 밖에서 실행 |
| 점령 TSV/JS | assertion 26개 | 26개 통과 | 모듈 로드가 아니라 runTests에 TSV 전달 |
| 선택 공간 실험 | 6개 | 6개 통과 | shapely·pyproj를 임시 제공, lock 변경 없음 |

0차의 1,353 통과는 최초 1,342 통과에 환경 프록시용 socksio 부재로 실패한 11개를
설치 후 재실행한 유효 결과를 합친 값이다. 이를 한 번의 전체 실행 결과로 읽지 않는다.
6차 전체 명령은 **1,395 passed, 129 skipped**였다. 129 중 런타임 DB skip은 128개
(PostGIS 접속 불가 97, 명시적 정책 DB URL 미설정 31)이며, 나머지 1개는 shapely 부재로
수집 전에 건너뛴 모듈이다. 선택 공간 실험 6개는 별도 실행했다.

추가 42개는 저장소 방향 검사 18개, 선택 서버 검사 11개, 도구 import 검사 순증 13개다.
기존 산책 lab의 scripts import item은 tools import item으로 대응한다. dev_console을
검사하던 6개 테스트는 3차의 의도적인 실행 입구 변경에 맞게 선택 서버를 검사한다.
파일 이름만 바꿔 옛 플래그 동작까지 유지했다고 주장하지 않는다.

HTTP 대조에서 옛 개발 모드의 health는 공용 서버에서, 검토 요청은 선택 서버에서 실행했다.
독립 기록 도구는 외부 fetch 없이 합성 입력으로 실행했고 시즌은 임시 SQLite에 생성·재시작했다.
시설 도구는 공개 표본·설정 미연결 상태를 확인했다. 운영 데이터·실제 외부 제공사·유료 모델은
호출하지 않았다.

정적 파일 17개·시즌 SQLite 스키마·게임 정책과 계약의 내용 보존은 4·5차에서 대조했고,
6차에서도 seed 원문·Alembic 전체 리비전이 0차와 같음을 확인했다. ruff도 통과했다.

## 승격 추적과 실험 유지

원장의 source/target 커밋·대상 저장소·운영 경로는 그대로다. 기존 추적 폴더에서 이동한
아래 3개 경로만 추가했다. 옛 디렉터리는 다른 파일과 삭제 이력을 추적하므로 유지한다.

| 기존 추적 범위 | 이어서 추적할 현재 파일 |
|---|---|
| Place의 tests/place | tests/tools/facility/test_facility_map_surface.py |
| Journey의 app/discovery | tools/place_intent/lab.py |
| Journey의 tests/discovery | tests/tools/place_intent/test_lab_surface.py |

기존 원장이 보던 검토 근거를 이어 보는 변경이며, 도구가 운영에 채택됐다는 뜻은 아니다.
게임·일기에는 아직 원장 항목이 없어 새 승격 기준을 임의로 만들지 않았다.
`python -m scripts.promotion_status`가 기존 source 커밋의 존재·조상 관계를 확인하고
보고를 마쳤다. PENDING은 후속 채택 검토 상태로 유지한다.

실험 7갈래는 현재 도구·테스트의 소비자 또는 문서의 재현 경로가 있어 유지한다.
실험 상태만으로 삭제하던 안내를 소비자·재현 근거를 확인하는 절차로 정리했다.
과거 연구·결정·Alembic의 출처 라벨과 import 검사에서 만든 임시 소스에 남은 옛 경로는
유효한 역사·검사 입력이다. 현재 문서의 제거된 /dev 화면 안내는 과거 참조임을 표시했다.

## 검증의 남은 한계

브라우저 실행 파일이 없으며 Playwright Chromium 다운로드도 timeout으로 실패했다.
시즌의 사진 재시도·새로고침·모바일 조작, GPS/기록의 JSON 저장·재입력·지도 렌더링,
시설 도구의 브라우저 통합 검사는 이 환경에서 재실행하지 못했다. HTTP·파일 보존 결과를
브라우저 조작 검증의 통과로 대신하지 않는다. 브라우저 가능 환경에서 각 도구 README의
검사를 이어 실행해야 한다.

5차 [CI](https://github.com/rkbuhtig/DAENGS_geo/actions/runs/34075751338)는 성공했다.
6차 코드의 PostGIS·Android CI 결과는 이 변경 PR의 체크에서 확인한다. 로컬 DB·Android
빌드와 실제 운영 제공사 호출은 이번 로컬 검증 범위에 포함되지 않는다.
