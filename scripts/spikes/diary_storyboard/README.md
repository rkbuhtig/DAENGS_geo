# 산책 세션 이해 → 스토리보드 → 선택적 일기 실험

## 현재 구현: 중심 생성 → 공통 배경 조립

[장면 조립 경계](../../../docs/explorations/walk/diary/scene-pipeline.md)를 따른다.
`scene_core.py`가 기록 중심·관측 중심과 보충 선택을, `scene_background.py`가 공통 배경 계약·조립을,
`scene_pipeline.py`가 준비·조회 요청 명세·고정 스탬프를 연결한다. 사용자 중심에는 동선·배경이 필수가 아니다.
`StampTool("action_background_v2", source, {"target_scene_count": 3})`로 새 경로를 사용한다.
`prepare_scene_plan` → `background_requests` → 외부 수집·응답 저장 → `StampTool`의 순서다.

```powershell
uv run python -m scripts.spikes.diary_storyboard.scene_pipeline_demo --target-scene-count 3 --out ../diary-lab/scene-pipeline-02
```

데모는 합성 응답을 파일로 저장한 뒤 같은 계약으로 읽는다. 여섯 조건의 `scene_plan.json`,
`background_requests.json`, `background_snapshot.json`, `prepared_stamps.json`, `stamp_book.json`과 보고서를 남긴다.
실제 외부 API·LLM 호출은 없다. 다음 v1 및 HOW 경로는 이전 결과 재현용이다.

## 앞선 구현: 행위·배경 분리와 부족분 보충 v1

[행위·배경 정책](../../../docs/explorations/walk/diary/action-background.md)을 따른다.
`StampTool("action_background", source, {"target_scene_count": 3})`는 사용자 기록을 먼저 보존하고,
부족한 장면만 체류·지속적인 속도 관측으로 보충한다. 3은 예시 인자이며 제품 기본값이 아니다.
`action_candidates.py`는 별도 관측 후보 풀, `action_background.py`는 보충 정책과 배경 분리를 소유한다.
LLM·네트워크 호출 없이 기존 책 조회·저장·재생 인터페이스로 확인할 수 있다.

```powershell
uv run python -m scripts.spikes.diary_storyboard.action_background_demo --target-scene-count 3 --out ../diary-lab/action-background-01
```

`report.json`에서 보충·미달을, `*/prepared_stamps.json`에서 행위와 배경을 확인한다.
`record_how`와 다음 작성 비교 실행기는 과거 실험 재현용으로 유지한다. 새 경로를 자동으로 모델에 발송하지 않는다.

## 공통 인터페이스와 앞선 실험: 독립 스탬프 툴

[스탬프 툴·카드 경계](../../../docs/explorations/walk/diary/stamp-tool.md)를 따른다.
`stamp_tool.py`는 원본·봉투에서 고정 스탬프를 만들고, `stamp_storyboard.py`는 선택·서술의
입출력을 처리한다. 카드에 시간·위치를 복사하지 않고 스탬프 버전을 참조한다.

```powershell
uv run python -m scripts.spikes.diary_storyboard.stamp_demo --out ../diary-lab/stamp-tool-01
```

합성 기록 6개의 새 입력 생성 + 이전 실제 응답 21카드 재생이다. 새 모델 호출은 없다.
출력 `records/write_request.json`, `*/storyboard.json`, `*/rendered.json`, `README.md`를 확인한다.
기존 출력 디렉터리를 덮어쓰지 않는다. 실제 provider 투영·새 HTTP 실행·사용자 편집 연결은 아직 별도 작업이다.

### HOW 추출과 스탬프 조립

별도 [HOW 재료 추출](../../../docs/explorations/walk/diary/how-materials.md)은
기존 canonical 동선에서 국소 체류·직선·큰 방향 전환·되짚기를 계산한다.
`how_materials.py`는 순수 계산·후보 조회, `how_demo.py`는 합성 10조건의 JSON·SVG·검토 HTML을 생성한다.
추출기 자체는 HOW 풀·스탬프 연결과 LLM 호출을 하지 않는다.
후속 `how_stamps.py`는 `StampTool("record_how", ...)`로 기록과 HOW를 조립한다.
`how_stamp_demo.py`에서 같은 동선의 사진·메모 6조건과 GPS 공백 1조건을 비교하고 HTML에서 근거를 선택해 본다.
입력·원본 구간·버전·실험 결과는 [HOW 조립 문서](../../../docs/explorations/walk/diary/how-stamps.md)에 있다.

```powershell
uv run python -m scripts.spikes.diary_storyboard.how_demo --out ../diary-lab/how-materials-01
uv run python -m scripts.spikes.diary_storyboard.how_stamp_demo --out ../diary-lab/how-stamps-01
```

두 실행 모두 네트워크·LLM 호출 없이 새 출력 디렉터리에 생성한다.

후속 [작성용 조각 비교](../../../docs/explorations/walk/diary/how-writing.md)는 스탬프 구성과 기록을 고정한 채
원래 입력과 짧은 HOW 딕셔너리를 나란히 보여준다. 원본 근거는 같은 책에 보존하며 모델을 호출하지 않는다.

```powershell
uv run python -m scripts.spikes.diary_storyboard.how_stamp_demo --writing-comparison --out ../diary-lab/how-writing-01
uv run pytest tests/spikes/diary_storyboard/test_writing_projection.py -q
```

`writing_comparison.json`의 두 입력·공통 프롬프트/스키마·참조 명세는 모두 준비 상태다.
`writing_projection.prepare_comparison`은 지정한 선택만 투영하며, `verify_comparison`과 `resolve_how`로 원본을 검산한다.
바이트 절감과 실제 모델 토큰·비용을 구별한다. 기존 `writing_request` 기본 출력은 바꾸지 않았다.

후속 [실제 HOW 작성 비교](../../../docs/research/2026-09-08-how-writing-gemini.md)는 같은 책·스탬프·프롬프트를
고정하고 세 조건의 두 입력을 각각 한 번 작성했다. 구조 통과 6/6, 입력 토큰 합계 61.6% 감소이며 의미 과장·문체 문제는 별도 기록했다.

```powershell
uv run python -m scripts.spikes.diary_storyboard.how_writing_experiment --source ../diary-lab/how-writing-03 --out ../diary-lab/how-writing-gemini-01
# --run을 붙이면 실제 Gemini 요청 최대 6회. 환경변수 또는 --env-file로 키를 읽는다.
uv run python -m scripts.spikes.diary_storyboard.how_writing_preview --out ../diary-lab/how-writing-gemini-01
uv run pytest tests/spikes/diary_storyboard/test_how_writing_experiment.py -q
```

기본은 입력 준비만 한다. 실패·중단된 요청은 재전송하지 않고 사용량 미확인 시 추가 호출도 멈춘다.
`manifest.json`은 고정 조건, `*/calls`는 실제 요청·응답·사용량, `results.json`은 구조 결과,
선택적인 `review.json`은 별도 검토 메모다. HTML 생성기는 저장 자료만 읽고 모델을 호출하지 않는다.

## 이전 전체 제작 흐름과 비교 실행기

[산책 일기 제작 계획](../../../docs/explorations/walk/diary/plan.md)의 실험 골격이다.
값·계산 정의·확보 범위와 추출 정책은 [자료 카탈로그](../../../docs/explorations/walk/diary/evidence-catalog.md)에 있다.
`app/`의 운영 경로와 DB에 연결하지 않고 로컬 파일로 전체 흐름을 실행한다.
초기 `fixtures/scenario.json`은 값을 직접 작성한 가상 산책이다. 후속 `acquire`는 합성 관측 GPS를
실제 geo 계산기에 넣어 공간 경향까지 계산하고, 저장된 실제 지도 응답과 연결한다.

## 구현 위치와 책임

| 파일 | 책임 |
|---|---|
| `contracts.py` | 자료 조각, 잠정 이해, 장면, 갱신·검토·일기 계약과 ID/시간 검사 |
| `evidence.py` | 이전 합성 시나리오를 자료 조각으로 옮기는 어댑터. 공간 조회·계산은 수행하지 않음 |
| `acquire.py` | fixture로 관측 GPS 생성, 별도 행동핀 작성, 생성 정답 분리, 입력·집계 영수증 저장 |
| `geo_adapter.py` | 관측 export → 기존 geo 계산·과거 공간 조회 → 자료 조각 |
| `cached_environment.py` | 저장 지도 응답의 조회 범위·시점·출처를 유지하며 현재 위치와 연결 |
| `verify_acquisition.py` | 저장 관측과 지도 응답으로 조각·집계 영수증 재계산 및 지문 대조 |
| `claim_experiment.py` | 행동 의미 정규화 후 같은 초안을 기존 재검토 / 근거 대조 후 수정으로 비교 |
| `compare_claim_runs.py` | 3쌍의 입력·초안·실제 지시·대조 결과 전달을 검증하고 호출 비용 집계 |
| `prompts.py` | 전체 이해·장면 갱신·재검토·일기 작성의 단계별 시스템 지시 |
| `provider.py` | Gemini 호출, 요청·응답·사용량 기록, 같은 요청의 저장 응답 재생 |
| `runner.py` | 단계 실행·재개, 검토·편집, 버전에 묶인 생성 여부 결정 |
| `storage.py` | 원자적 체크포인트 저장, 변경 기록, 읽기용 JSON/Markdown 출력 |
| `__main__.py` | start / advance / review / decide CLI |
| `verify_run.py` | 저장된 요청·단계 상태·검토본·재생 결과 대조 |

장면의 수·경계는 첫 이해 호출에서 모델이 제안한다. 장면별 중요도 점수나 재료별 우선순위는
코드에 두지 않았다. 첫 개요의 경계는 이번 실행 동안 유지하며 장면 분할·병합은 미구현이다.

이 설명은 기존 `understand` 흐름이다. 아래 후보 구성 실험은 별도 opt-in `select`/`compose` 단계를 사용하며 초기 구성에서 여러 사건을 묶을 수 있다. 두 흐름 모두 작성 순회 중 구성 변경은 지원하지 않는다.

## 사건/장면 구성 — 미커밋 후보 골격에서 이어받은 오프라인 실험

`selection_adapter.py`는 저장된 Gemini 3차 **입력만** 기존 Evidence와 CandidateCatalog로 옮긴다. 모델의 출력·검토는 근거로 가져오지 않는다. `candidates.py`는 원본 point/interval과 선정 계약을 검사한다. 원본 해시는 유지하며 실험의 절대 시작 시각은 명시적인 합성값이다. 지도 좌표를 보존하지 않은 자료이므로 위치 상태는 unresolved다.

`composition_mode=individual`은 기존 1사건=1장면, `grouped`는 SceneComposition의 포함/맥락 사건과 대표 사건을 통해 여러 사건을 한 장면으로 편집한다. 관측 범위는 합치지 않는다. 필수 행동은 한 장면의 포함 기록으로 남고 맥락은 여러 장면에서 공유할 수 있다. 서로 다른 chain·GPS 공백을 가로지른 묶음, 중복 소유, 필수 행동의 맥락 전용 처리, 대표 사건 시간 확장과 잘못된 생략 이유를 거부한다.

```powershell
# 키·네트워크 없이 개요만 생성. 새 출력 디렉터리를 사용한다.
uv run python -m scripts.spikes.diary_storyboard.selection_demo --case actions --composition individual --steps 1 --run ../diary-lab/events-individual
uv run python -m scripts.spikes.diary_storyboard.selection_demo --case actions --composition grouped --steps 1 --run ../diary-lab/events-grouped
# 같은 명령에서 --steps를 빼면 가짜 모델로 작성·재검토까지 이어간다.
uv run python -m scripts.spikes.diary_storyboard.selection_demo --case actions --composition grouped --run ../diary-lab/events-grouped
uv run python -m scripts.spikes.diary_storyboard.verify_run --run ../diary-lab/events-grouped
```

`--case movement|actions|gap`으로 세 조건을 읽는다. 기본 archive는 레포의 `docs/research/2026-09-07-walk-diary-evidence/gemini-03.json`이다. FixtureProvider는 네트워크를 호출하지 않는다. 같은 비교 대상 사건을 시간순 최대 3개씩 묶는 것은 **배선 검산용 설정**이며 선정 정책이나 품질 실험이 아니다. 모델 프롬프트에는 이 3개 묶음 규칙이 없다. 사건별 자료와 사용 범위를 유지하면서 구성만 달라지는지 확인한다.

`storyboard.md`는 본문 작성 전에도 구성·원본 시각을 보여준다. 작성 요청과 검토 완료본은 구성 참조와 각 사건의 출처·시각·원문 조각을 갖는다. 개요 시각은 대표 사건의 시각이지 사진·냄새 등의 전체 지속시간이 아니다. 구조 검사 통과는 문장 의미 검증 완료가 아니다.

기존 run은 선택 프롬프트/스키마 지문이 다르면 새 실행을 요구한다. 이 변경으로 예전 미커밋 단계에서 만든 선택 run의 재개는 거부될 수 있다. 원본 run을 덮어쓰지 않는다. 운영 지도 연결, 주장 단위 의미 검사, 동적 재구성은 후속이다.

### 실제 모델의 구성 A/B

```powershell
# 준비만 수행: 외부 호출 없음
uv run python -m scripts.spikes.diary_storyboard.composition_experiment --out ../diary-lab/composition-ab
# GEMINI_API_KEY/GOOGLE_API_KEY 환경변수를 준비한 뒤 실제 구성 호출
uv run python -m scripts.spikes.diary_storyboard.composition_experiment --out ../diary-lab/composition-ab --run
```

movement/actions/gap × individual/grouped의 최대 6회 요청이다. 본문 작성과 자동 재시도는 없다. 중단되거나 거부된 호출도 동일 명령 재실행 시 다시 보내지 않는다. 설정·지시·자료가 달라지면 새 출력 디렉터리가 필요하다. 이 실험에는 일반 `advance`를 사용하지 않는다. `--env-file`도 지원한다.

`experiment.json`은 설정과 요청 지문, 각 run의 `planned_request.json`은 전송 예정 요청, `calls`는 실제 요청·응답·영수증, `results.json`과 `README.md`는 승인 상태와 미검증 제안을 구분해 보존한다. 100,000토큰 중단 기준은 다음 요청 전에 확인된 사용량을 검사하는 기준이며 총비용의 엄격한 상한이 아니다.

[첫 실제 비교](../../../docs/research/2026-09-08-event-scene-gemini-ab.md)는 응답 6/6, 구조 통과 0/6이었다. 공용 응답 스키마와 시간 재작성 계약의 문제를 기록했다. 현재 명령은 당시 조건 보존용이며 개선된 계약은 아직 반영하지 않았다.

후속 `editorial_contract.py`는 A/B별 사건 ID 전용 스키마를 제공한다. 모델은 시각·좌표·근거 ID·중복 결정표를 쓰지 않는다. `editorial_experiment.py`가 응답을 검증한 뒤 기존 SelectionPlan으로 변환한다. `resolved_plan.json`과 `resolved_scene_scopes.json`은 시스템 출력이며 API 원문과 구분한다. 대표 사건 시각과 포함 사건의 편집 범위는 다른 값이다. 보존 입력에 없는 좌표는 복원하지 않는다.

```powershell
uv run python -m scripts.spikes.diary_storyboard.editorial_experiment --out ../diary-lab/editorial-ab
uv run python -m scripts.spikes.diary_storyboard.editorial_experiment --out ../diary-lab/editorial-ab --run
```

같은 6회 제한·재전송 금지·준비 전용 기본값을 사용하며 `--env-file`을 지원한다. 전용 명령이 요청·자료·설정·변환 코드 지문을 검사한다. 일반 `advance`나 기존 `verify_run`은 v2 변환 provider를 자동 선택하지 않으므로 이 실행의 재개·재생 검증에 사용하지 않는다. 코드 수준의 정확한 재생은 `EditorialProvider(..., replay_from=source)`와 `step`으로 검증했다. [ID 계약의 실제 비교](../../../docs/research/2026-09-08-event-scene-gemini-ab-v2.md)는 3/6 구조 통과였으며, 편집 모순·GPS 맥락 연결·의미 과장은 별도로 남았다.

## 실행

### 공간·액션 슬롯 → 스탬프 → 짧은 작성

`stamp_materials.py`는 보존 V3 입력을 제한된 어휘 어댑터로 구조화하고 공간·액션 풀을 따로 관리한다. 스탬프 중심·맥락·상대 시간은 시스템이 고정한다. 원자료 이력과 활성 슬롯을 구분하며, 슬롯 교체는 공간 이탈이나 스탬프 생성 계기가 아니다. 현재 원본 기록/봉투 계약과의 운영 어댑터는 아직 연결하지 않았다.

```powershell
# 자료와 선택 요청 준비만 수행, 네트워크 없음
uv run python -m scripts.spikes.diary_storyboard.stamp_experiment --out ../diary-lab/slot-stamps
# 선택 → 선택된 스탬프만 짧은 작성, 세 조건 최대 6회
uv run python -m scripts.spikes.diary_storyboard.stamp_experiment --out ../diary-lab/slot-stamps --run
```

키는 기존 환경변수 또는 `--env-file`로 전달한다. 재개에는 같은 전용 명령을 사용한다. 실패/중단 호출 자동 재시도는 없고 입력·프롬프트·코드 지문이 달라지면 새 출력 디렉터리를 요구한다. 일반 `advance`는 이 별도 실험을 실행하지 않는다. `materials.json`은 원본 스탬프·이력·정책·지문, `select/write/accepted.json`은 구조 검사 후 결과다. accepted는 의미 정확성 승인이 아니다. [실제 첫 스탬프 비교](../../../docs/research/2026-09-08-slot-stamp-gemini.md)에 결과와 남은 오류를 기록했다.

모든 명령은 **Geo 루트** 기준이다. Python 3.12와 `uv sync --frozen`으로 준비하며
기존 `pydantic`, `httpx` 외 추가 의존성은 없다. 예시의 `../diary-lab/`은 저장소 밖의
실험 디렉터리다. 출력과 캐시를 구분해 두고 실제 보관 위치에 맞게 바꾼다.

### 키·외부 캐시 없이 먼저 검증

```bash
uv run python -m scripts.spikes.diary_storyboard --help
uv run pytest tests/spikes/diary_storyboard tests/test_script_imports.py -k diary -q
```

회귀 테스트는 합성 입력·가짜 모델·임시 캐시로 계산과 검토 흐름을 실행한다. DB·실제 API 키·
저장된 모델 응답이 필요 없다. CLI의 `start`는 가짜 모델 모드가 아니므로 다음 조건을 준비한다.

| 실행 | 준비할 자료 | 외부 호출 |
|---|---|---|
| `acquire` / `verify_acquisition` | recipe와 해당 recipe의 저장 지도 응답 | 없음; 캐시를 새로 수집하지 않음 |
| `start` / `advance` | 수기 fixture 또는 계산된 evidence, Gemini 키 | 모델 호출; 마지막 완료 상태까지 도달했으면 재사용 |
| `review` / `decide --choice skip` | 기존 run과 현재 검토 버전 | 없음 |
| `decide --choice generate` | 검토된 run과 Gemini 키 | 별도 일기 생성 요청 |
| `--replay-from` / `verify_run` | 같은 입력·설정으로 이미 저장한 run | 저장 응답 재생, 실제 호출 없음 |

실제 호출은 `GEMINI_API_KEY` 또는 `GOOGLE_API_KEY` 환경변수를 준비하거나 예시의
`../diary-lab/keys.env`를 만든다. 키 파일은 해당 dotenv 이름과 기존 `gemini: ...` 형식을 읽는다.
모델 기본값은 비교 실험용 `gemini-3.1-flash-lite`이며 `start --model`로 바꿀 수 있다.
모델 선택을 최적화한 결과라는 뜻은 아니다. `claim_experiment`도 실제 모델을 호출하는 별도 비교다.

### 계산 입력으로 실행

```powershell
uv run python -m scripts.spikes.diary_storyboard.acquire --cache-dir ../diary-lab/environment-cache --out ../diary-lab/my-input
uv run python -m scripts.spikes.diary_storyboard.verify_acquisition --dataset ../diary-lab/my-input --cache-dir ../diary-lab/environment-cache
uv run python -m scripts.spikes.diary_storyboard start --input ../diary-lab/my-input/evidence.json --run ../diary-lab/my-run --env-file ../diary-lab/keys.env
```

`--recipe`로 생성·조회 조건을 바꿀 수 있다. 기본값은 `fixtures/acquisition.json`이다.
이번 경로·과거 15개 경로·노이즈·핀은 합성이다. 관측 export만 계산기에 넘기고 생성기의
정답·의도·seed는 `evaluation/`에 분리한다. `observations/`, `pins.json`, `evidence.json`,
`calculation_audit.json`, `acquisition_receipt.json`, `INPUT_REPORT.md`를 출력한다.

기본 조회 대상은 저속 관측 중심·행동핀·경로 양끝이다. 지정 기간과 반려견으로 과거 산책을
선택하고 30m 반경, 8u 붓, 빈 장 포함, 조건 필터 없음으로 읽는다. 시간대 필터는
`Asia/Seoul` 기준이다. 이 값들은 실험 조건이며 장면 수·우선순위 정책이 아니다.

환경 캐시는 저장소에 포함하지 않는다. [기본 recipe](fixtures/acquisition.json)에 나열된 Kakao 응답 6개
(`A_address.json`, `A_CE7.json`, `A_FD6.json`, `B_address.json`, `B_CE7.json`, `B_FD6.json`)가
`--cache-dir`에 필요하다. 이 CLI는 기존 좌표 실험의 저장 응답을 소비하며 수집기는 제공하지 않는다.
각 JSON은 `name`, `endpoint`, `query`, `fetched_at`, `http_status`,
`response_sha256`, `data`를 가진 기존 좌표 실험의 저장 형식이다. 현재 조회 대상과 기존 조회
중심이 15m 이내일 때 연결하며, 시설 결과의 원래 조회 반경 250m를 유지한다. 자료 없는 위치는
시설 0개로 바꾸지 않는다. 당시 날씨·공원 내부 여부·실제 시설 방문은 제공하지 않는다.
실제 응답의 원문 지문과 저장 JSON 지문을 구별하고 연락처 등 불필요 필드는 투영에서 뺀다.

캐시가 없다면 위 회귀 검증부터 실행한다. 공간 계산만 비교하려면 기본 recipe를 저장소 밖에
복사해 `environment_snapshots`를 빈 배열로 바꾸고 `acquire --recipe <복사한 파일>`을 지정할 수 있다.
이때 환경 조각은 `no_source`(연결할 저장 질의 없음)로 남으며, 실제 환경 자료를 연결한 실행과
같은 결과로 보지 않는다.

### 초기 수기 시나리오로 실행

```powershell
uv run python -m scripts.spikes.diary_storyboard start --run ../diary-lab/my-run --env-file ../diary-lab/keys.env
```

환경변수로 키를 준비했다면 `--env-file`을 생략한다. 키는 요청 헤더로만 전송하고 저장하지 않는다.
출력 디렉터리는 저장소 밖에 둔다. start는 비어 있지 않은 디렉터리를 덮어쓰지 않는다.
사용자 자료를 붙이면 스냅샷과 요청·응답에 그 자료가 포함된다는 점도 출력 보관에 반영한다.

실패하면 마지막 완료 단계부터 재개한다. 실패한 호출의 자료를 유지하고 새 호출을 기록한다.

```powershell
uv run python -m scripts.spikes.diary_storyboard advance --run ../diary-lab/my-run --env-file ../diary-lab/keys.env
```

원자료나 프롬프트가 달라졌으면 새 run을 만든다. 자동 무한 재시도는 없다.
스토리보드 완성 시 `awaiting_review`에서 멈추며 일기는 생성하지 않는다.

`storyboard.md`를 읽고 필요하면 아래 형식의 JSON 파일을 만들어 검토에 전달한다.
ID는 해당 실행의 모델 출력에서 가져온다. 생략한 장면과 필드는 기존 사용자 편집을 유지한다.
`text: null`은 해당 문구 편집을 해제해 모델 문구로 돌아가는 의미다.

```json
[
  {"scene_id": "scene_01", "text": "보호자가 정정한 장면 문구"},
  {"scene_id": "scene_02", "included": false}
]
```

```powershell
$revision = (Get-Content -Raw -Encoding UTF8 ../diary-lab/my-run/storyboard.json | ConvertFrom-Json).revision
uv run python -m scripts.spikes.diary_storyboard review --run ../diary-lab/my-run --expected-revision $revision --actor human --reviewer owner --edits ../my-edits.json
```

`--expected-revision`은 직접 확인한 현재 출력 버전으로 지정한다. 위 PowerShell 명령은 그 값을 읽는다.
편집 없이 검토하려면
`--edits`를 생략한다. 테스트에서 검토를 모사할 때는 `--actor simulated`를 명시한다.
review 명령도 모델을 호출하지 않으며 검토된 새 버전을 저장한다.

```powershell
# review가 저장한 새 버전을 확인하고 일기 생성을 건너뛴다.
$revision = (Get-Content -Raw -Encoding UTF8 ../diary-lab/my-run/storyboard.json | ConvertFrom-Json).revision
uv run python -m scripts.spikes.diary_storyboard decide --run ../diary-lab/my-run --expected-revision $revision --choice skip
```

일기 생성을 요청할 때는 검토된 버전을 확인한 뒤 별도로 실행한다.

```powershell
$revision = (Get-Content -Raw -Encoding UTF8 ../diary-lab/my-run/storyboard.json | ConvertFrom-Json).revision
uv run python -m scripts.spikes.diary_storyboard decide --run ../diary-lab/my-run --expected-revision $revision --choice generate --env-file ../diary-lab/keys.env
```

skip은 호출 0회이며 이후 generate를 선택할 수 있다. generate는 검토본의 포함 장면으로 일기를
작성한다. 같은 검토 버전·같은 선택에 이미 완료 결과가 있으면 재사용한다. 숨긴 장면의 편집
문구도 생성 입력에서 제외한다. 편집한 본문은 이전 모델의 사실·해석 목록이 덮어쓰지 않도록
생성용 투영에서 그 목록 대신 편집 문구를 전달한다. 편집 전 자료는 상태 파일에 남는다.

## 산출물과 재현

```text
run/
  config.json                 모델·프롬프트·자료 지문
  evidence_snapshot.json      실행 동안 유지하는 원자료 조각
  states/000000.json ...      단계별 이해·장면·검토의 전체 버전
  calls/000001/ ...           요청·응답·원 응답·사용량·오류 영수증
  stage_errors/               구조 검증 등에 실패한 단계 기록
  revision_log.json           이해 변경 이유·근거·영향받은 장면
  storyboard.json / .md       현재 상태의 읽기용 출력
  decisions/<버전>-<선택>/    선택 기록·생성 입력 스냅샷·결과·일기
```

`states/`의 마지막 완료 파일이 재개의 기준이다. 보기용 출력은 advance로 다시 만들 수 있다.
동일 run을 여러 프로세스가 동시에 수정하는 실행은 지원하지 않는다. 네트워크 응답 뒤
체크포인트 저장 전 프로세스가 종료되면 재개 시 해당 호출 비용이 중복될 수 있다.

저장된 요청과 모델이 일치할 때 실제 네트워크 없이 응답을 재생할 수 있다.

```powershell
uv run python -m scripts.spikes.diary_storyboard start --input ../diary-lab/my-input/evidence.json --run ../diary-lab/replay --replay-from ../diary-lab/my-run
```

위 재생 예시는 계산 입력 run 기준이다. 수기 기본 시나리오로 실행했으면 `--input`을 생략한다.
모델을 바꿨다면 원 실행과 같은 `--model`도 지정한다. 같은 review 입력을 적용하고
decide에 `--replay-from`을 주면 일기도 재생한다.
입력·모델·프롬프트·스키마·앞선 상태가 달라져 요청 지문이 다르면 재생을 거부한다.
수정한 프롬프트를 옛 응답으로 평가하는 용도로 사용하지 않는다.

## 검증과 남은 경계

### 행동 정규화·근거 대조 비교

같은 계산 입력으로 세 번의 초안을 만들고, 각 초안을 두 조건으로 나눈다. 아래 명령의
`--pair`를 1, 2, 3으로 바꿔 **순차 실행**한다. 재개도 동일 명령을 사용한다.

```powershell
uv run python -m scripts.spikes.diary_storyboard.claim_experiment --input ../diary-lab/my-input/evidence.json --root ../diary-lab/my-comparison --pair 1 --env-file ../diary-lab/keys.env
uv run python -m scripts.spikes.diary_storyboard.compare_claim_runs --root ../diary-lab/my-comparison
```

비교 검증기는 세 쌍이 모두 완료된 뒤 실행한다. 생성한 각 run의 자료는 기존 `verify_run`으로도
검증할 수 있다. 조건별 재개에는 `claim_experiment`를 사용한다. 추가 지시·정규화 지문은
상위 `experiment.json`에 저장하며 변경 시 새 root를 요구한다. 기존 `advance`는 이 추가
대조 단계를 실행하지 않으므로 실험 조건의 재개에 사용하지 않는다.

두 번째 조건은 초안 작성 응답만 정확히 재생하고 대조·수정은 실제 호출한다. 모든 텍스트
필드를 대조 목록에 포함하지만, 한 문단 안의 주장을 각각 분해하는 구현은 아니다.
대조 모델의 판정은 정답이 아니다. 단계당 최대 3회 시도하고, 429·503은 30초 대기한다.
실패·체크포인트는 보존하며 사용자 검토나 일기 생성 없이 멈춘다.
[실제 3쌍 비교 결과](../../../docs/research/2026-09-06-diary-claim-comparison.md)는 대조 후에도
장면 수정이 없었다. 초기 요청이 몰려 429가 발생한 뒤 순차 재개한 과정까지 기록했다.

### 회귀 검증

```powershell
uv run pytest tests/spikes/diary_storyboard tests/test_script_imports.py -k diary -q
uv run ruff check scripts/spikes/diary_storyboard tests/spikes/diary_storyboard
uv run python -m scripts.spikes.diary_storyboard.verify_run --run ../diary-lab/my-run
```

회귀 검증은 상태 전달·장면 교체·재개·근거 ID·시간 범위·원자료 변경·검토 버전·숨김/편집·
생성 선택·중복 요청을 다룬다. 가짜 모델 문구로 실제 LLM의 서술 품질을 평가하지 않는다.
[실제 Gemini 실행 결과](../../../docs/research/2026-09-06-diary-storyboard-skeleton.md)는 별도로 기록한다.
계산 입력의 질량 보존·산책별 중복 집계 방지·분모 변경·빈 자료·시간대 선택·생성 정답 유출 방지·
환경 조회 범위도 검증한다. [계산 입력을 연결한 후속 실행](../../../docs/research/2026-09-06-diary-geo-observed-inputs.md)은
스토리보드 검토 대기에서 멈췄다. 재생 시 원 실행과 같은 `--input`도 전달해야 한다.

실기기 관측·운영 환경 조회 연결, 앱 검토 UI, 서버 영속/동기화, 장면 경계
재구성, 편집 이후 의미 재검토, 큰 입력의 분할·비용 제어는 후속 작업이다. 모델 재검토는
오류를 발견하기 위한 단계이며 사실성 보장이 아니다. 근거 ID가 유효해도 주장이 참인 것은 아니다.
