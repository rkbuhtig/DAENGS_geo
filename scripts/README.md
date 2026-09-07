# scripts/ — 명령·생성기·검증·갈래별 실험

반복 실행하는 명령은 목적과 소비자에 따라 아래 위치에서 관리한다.
공용 app 내부의 계층은 [결정 #67](../docs/decisions/2026-08-26-package-architecture.md),
검증의 소유권은 [tests 안내](../tests/README.md)를 따른다.

기준은 **개수가 아니라 수명**이다.

저장소 경계는 [결정 #86](../docs/decisions/2026-09-07-repository-execution-boundaries.md)을
따른다. scripts와 tools는 app을 소비할 수 있지만, app에서 scripts/tools/tests로 향하는
새 import는 금지한다. 반복해서 조작하는 검토 화면·HTTP 어댑터는 tools가 소유하고
공용 생성기는 sim에 남긴다. 도구별 위치·실행 조건은 [tools 안내](../tools/README.md)를 따른다. 기존 독립 실행 명령은 유지한다.

| | 무엇 | 언제 사라지나 |
|---|---|---|
| `scripts/*.py` | README가 안내하는 정식 관리·실행 명령 | 그 워크플로가 없어질 때 |
| `verify/` | 관통 검증 하네스. 같은 경로를 여러 단계가 다시 쓴다 | 검증 대상이 없어질 때 |
| `sim/` | 재현 가능한 생성기. truth·센서 관측·전달을 분리해 실패를 비교한다 | 해당 계약을 대체할 때 |
| `spikes/<갈래>/` | 기획·가설별 실험과 재현 장치 | 종료 판단과 소비자·재현 경로 확인 뒤 |

## `spikes/` — 갈래별 실험과 재현

| 갈래 | 질문·현재 실행 입구 |
|---|---|
| `diary_storyboard/` | 전체 이해·장면 갱신·보호자 검토·별도 생성 요청. [실행](spikes/diary_storyboard/README.md) |
| `storyboard_and_regions/` | 합성 산책과 저장된 세계 자료로 장면·동네 구간 비교. [실행](spikes/storyboard_and_regions/README.md) |
| `territory_paint/` | 공간 붓·분포·센서 오염·저장 후보 비교. [기준 탐색](../docs/explorations/walk/spatial/territory-paint.md) |
| `territory_production_plan/` | 지도·촬영·페이크 판정의 제작 가설과 공통 TSV. [실행](spikes/territory_production_plan/README.md) |
| `territory_season/` | 시즌 전략 시뮬레이션과 검토 서버의 기존 CLI. [실행](spikes/territory_season/README.md) |
| `walk_diary_route/` | 경로 마스킹·양자화·단순화의 노출/충실도 비교. [기준 탐색](../docs/explorations/walk/diary/walk-diary-route.md) |
| `walk_record_lab/` | 행동·환경·종료 결과와 자료 선택 비교. [실행](spikes/walk_record_lab/README.md) |

재사용되는 검토 HTTP·화면은 `tools/`에 있다. 특정 실험의 결과 HTML·제작 시안·재현
페이지는 해당 실험과 함께 유지한다. 아래는 공간 분포 실험의 명령 예다.

```bash
uv run python -m scripts.spikes.territory_paint.persona_year --cache osm.json --json personas.json
uv run python -m scripts.spikes.territory_paint.storage_candidates --personas personas.json
```

### 갈래를 닫을 때

갈래 상태가 `adopted`나 `rejected`로 바뀌면 종료 여부를 검토한다. 상태만으로 코드를
자동 삭제하지 않는다. 제품 보류와 죽은 코드는 구분하고, 실행 중인 도구·다른 실험·테스트가
소비하거나 현재 판단을 재현하는 코드라면 유지한다.

종료할 때는 import와 문서 참조를 확인하고, 소비자가 더 이상 없으며 결과를 다시 찾을
수 있을 때 제거한다. 삭제한 구현은 연구 문서의 `재현` 절에서 해당 커밋·옛 경로로 연결한다.
예를 들어 `region_fidelity.py`는 공간 셀·영역 계산의 근거이므로 참조를 확인하지 않고
삭제할 대상이 아니다.

```bash
rg -n 'scripts[./]spikes[./]<갈래>' app tools scripts tests docs android
```

**여기 있는 모든 모듈은 import 되는 것이 테스트로 지켜진다** (`tests/test_script_imports.py`).
`ruff` 는 import 대상을 해석하지 않고 `compileall` 은 문법만 본다 — 둘 다 통과하면서 깨져
있을 수 있어서 실제로 import 해 본다. 발견식이라 새 폴더도 저절로 들어온다.

새 갈래의 스파이크는 새 폴더를 만든다. 갈래 없이 스파이크를 추가하지 않는다 — 소속이
없으면 지울 시점도 없기 때문이고, 그게 이 폴더가 쌓인 이유였다.

`spikes/storyboard_and_regions`는 [산책 스토리보드와 동네 구간](../docs/explorations/walk/diary/storyboard-and-regions.md)
갈래의 로컬 실험이다. 합성 산책과 SGIS·상가·공원·하천 snapshot으로 자동 재생 HTML을 만든다.
기본 재생성은 네트워크를 쓰지 않고, 자료 수집에만 명시적인 `--fetch`가 필요하다.
원본 자료·인증키·산출물은 저장소 밖에 둔다.
[실행 방법](spikes/storyboard_and_regions/README.md)과
[실측 결과](../docs/research/2026-09-04-storyboard-regions-spike.md)를 참고한다.

## `verify/` — 스파이크가 아니다

산책 관통 검증 넷은 한 세트다. `walk_fixture.py` 가 좌표의 유일한 원천이고,
`walk_pipeline_check.py`(서버 단독) → `walk_emulator_drive.py`(에뮬레이터 주입) →
`walk_bundle.py`(실측 회수) 가 그걸 같이 읽는다. 단계를 나눈 이유는 실패 원인을 좁히기
위해서고 (`walk_pipeline_check.py` 도크스트링), 검증할 때마다 다시 쓴다. 측정이 아니라
도구다.

## `sim/` — 제품 데이터도 일회성 fixture도 아니다

`sim/walk`는 지도 독립 행동과 로컬 polyline으로 연속 motion truth를 만든 뒤 센서 관측과 앱
전달을 따로 오염한다. 저장한 `walk-trace-scenario-v1`을 다시 실행할 수 있고, 결과의
`walk-export.json`만 기존 제품 계산기로 들어간다. 사용법과 층별 출력은
[`simulator-core.md`](../docs/explorations/walk/recording/simulator-core.md)에 둔다.

## 최상위

최상위에 남는 것은 **README 나 문서가 실행을 지시하는 명령**뿐이다.
`detect_schema_revision.py` 는 [README 의 스키마 절](../README.md)이,
`facility_pet_coverage.py` 는 [pet-axes 갈래](../docs/explorations/facility/pet-axes.md)가
부른다. 소속이 애매하면 최상위가 아니라 `spikes/<갈래>/` 다.

`source_fact_coverage.py`는 [source-facts 갈래](../docs/explorations/facility/source-facts.md)가
부른다. 현재 KTO 저장 레코드를 순수 projector에 통과시켜 scope·predicate·amenity·실패 수를
읽기 전용으로 다시 잰다.

`discover_place_tags.py`는 [제안 #72](../docs/decisions/2026-08-27-place-tag-catalog.md)의
**발견** 칸이다. 승인된 이름 태그 catalog와 ingest 경로는 아직 구현되지 않았고,
`app/place/tag_catalog.py`는 그 제안이 가리키는 예정 경로다. 이 도구는 후보를 다시 뽑는
작업대라 최상위에 있지만, 출력만으로 현재 제품 데이터가 바뀌지는 않는다.
이 도구의 출력은 **후보일 뿐 어떤 행에도 저장되지 않는다** (#70 §8: 임베딩 자동 분류 기각).
임베딩 모드는 레포 의존성 밖이라 `uv run --with sentence-transformers --with scikit-learn` 이
필요하고, `--mode mine` 만 추가 의존성 없이 돈다.

`spikes/walk_diary_route`는 단일 산책 일기 동선을 영구 계약으로 만들기 전에 시작·종료
마스킹, 양자화, 단순화가 노출과 충실도에 주는 영향을 비교한다. 출력 좌표는 개발용 민감
payload이며 저장 승인이 아니다.

```bash
uv run python -m scripts.spikes.walk_diary_route.report
```

`evaluate_place_intent.py`는 [intent-planner 갈래](../docs/explorations/facility/intent-planner.md)의
LLM 의미 제안 평가기다. 기본 실행은 저장된 fixture만 읽고 네트워크를 쓰지 않는다. `--live`는
명시적으로 OpenAI 설정과 `DAENGS_USAGE_POLICY=dev`를 제공했을 때만 기존 Usage Gate를 거쳐
실측한다. CI는 모델 가용성·비용·출력 변동을 품지 않고 녹화 출력과 평가 수식만 검증한다.

```bash
uv run python -m scripts.evaluate_place_intent
```

`promotion_status.py`는 [승격 원장](../docs/promotion-ledger.toml)의 source 기준점 뒤에서
운영 표면 관련 경로가 얼마나 달라졌는지 읽기 전용으로 보고한다. `pending`은 실패가 아니라
승격 검토 재료다. CI도 이 명령을 실행하지만 실험 중 차이를 막지 않는다.

```bash
uv run python -m scripts.promotion_status
```

`export_copy.py`는 `DAENGS_dev/geo` 전체 사본을 만들던 **과거 이관 도구**다. 지금 운영
Place/Journey는 `DAENGS_dev/{place-search,journey-service}`, Android는 `DAENGS_app`이
canonical이라 현재 승격에 쓰지 않는다. 히스토리 재현이 꼭 필요할 때만 오출력을 막는
`--legacy-export` 플래그를 명시한다.

```bash
uv run python -m scripts.export_copy --legacy-export <빈 임시 폴더>
```
