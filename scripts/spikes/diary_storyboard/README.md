# 산책 세션 이해 → 스토리보드 → 선택적 일기 실험

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

## 실행

geo 루트에서 프로젝트의 Python 3.12 환경을 쓴다. 기존 `pydantic`, `httpx` 외 추가 의존성은 없다.
아래 경로는 이 워크스페이스의 예이며 출력 위치와 키 파일은 바꿀 수 있다. 모델은 앞 실험과
비교하기 위해 `gemini-3.1-flash-lite`를 기본값으로 사용하며 `--model`로 바꿀 수 있다.
모델 선택을 최적화한 결과라는 뜻은 아니다.

### 계산 입력으로 실행

```powershell
uv run python -m scripts.spikes.diary_storyboard.acquire --cache-dir ../experiments/coordinate_narration/cache --out ../experiments/diary_storyboard_geo/my-input
uv run python -m scripts.spikes.diary_storyboard.verify_acquisition --dataset ../experiments/diary_storyboard_geo/my-input --cache-dir ../experiments/coordinate_narration/cache
uv run python -m scripts.spikes.diary_storyboard start --input ../experiments/diary_storyboard_geo/my-input/evidence.json --run ../experiments/diary_storyboard_geo/my-run --env-file C:/Users/Administrator/Downloads/forwork/env
```

`--recipe`로 생성·조회 조건을 바꿀 수 있다. 기본값은 `fixtures/acquisition.json`이다.
이번 경로·과거 15개 경로·노이즈·핀은 합성이다. 관측 export만 계산기에 넘기고 생성기의
정답·의도·seed는 `evaluation/`에 분리한다. `observations/`, `pins.json`, `evidence.json`,
`calculation_audit.json`, `acquisition_receipt.json`, `INPUT_REPORT.md`를 출력한다.

기본 조회 대상은 저속 관측 중심·행동핀·경로 양끝이다. 지정 기간과 반려견으로 과거 산책을
선택하고 30m 반경, 8u 붓, 빈 장 포함, 조건 필터 없음으로 읽는다. 시간대 필터는
`Asia/Seoul` 기준이다. 이 값들은 실험 조건이며 장면 수·우선순위 정책이 아니다.

환경 캐시는 저장소에 포함하지 않는다. 기본 recipe에 나열된 Kakao 응답 6개가 외부 캐시
폴더에 필요하다. 각 JSON은 `name`, `endpoint`, `query`, `fetched_at`, `http_status`,
`response_sha256`, `data`를 가진 기존 좌표 실험의 저장 형식이다. 현재 조회 대상과 기존 조회
중심이 15m 이내일 때 연결하며, 시설 결과의 원래 조회 반경 250m를 유지한다. 자료 없는 위치는
시설 0개로 바꾸지 않는다. 당시 날씨·공원 내부 여부·실제 시설 방문은 제공하지 않는다.
실제 응답의 원문 지문과 저장 JSON 지문을 구별하고 연락처 등 불필요 필드는 투영에서 뺀다.

### 초기 수기 시나리오로 실행

```powershell
uv run python -m scripts.spikes.diary_storyboard start --run ../experiments/diary_storyboard_geo/my-run --env-file C:/Users/Administrator/Downloads/forwork/env
```

`GEMINI_API_KEY` 또는 `GOOGLE_API_KEY` 환경변수도 지원한다. 키 파일은 같은 dotenv 이름과
기존 로컬 파일의 `gemini: ...` 형식을 읽는다. 키는 요청 헤더로만 전송하고 저장하지 않는다.
출력 디렉터리는 저장소 밖에 둔다. start는 비어 있지 않은 디렉터리를 덮어쓰지 않는다.
사용자 자료를 붙이면 스냅샷과 요청·응답에 그 자료가 포함된다는 점도 출력 보관에 반영한다.

실패하면 마지막 완료 단계부터 재개한다. 실패한 호출의 자료를 유지하고 새 호출을 기록한다.

```powershell
uv run python -m scripts.spikes.diary_storyboard advance --run ../experiments/diary_storyboard_geo/my-run --env-file C:/Users/Administrator/Downloads/forwork/env
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
uv run python -m scripts.spikes.diary_storyboard review --run ../experiments/diary_storyboard_geo/my-run --expected-revision 4 --actor human --reviewer owner --edits ../my-edits.json
```

`--expected-revision`은 예시 숫자가 아니라 현재 출력 버전으로 지정한다. 편집 없이 검토하려면
`--edits`를 생략한다. 테스트에서 검토를 모사할 때는 `--actor simulated`를 명시한다.
review 명령도 모델을 호출하지 않으며 검토된 새 버전을 저장한다.

```powershell
uv run python -m scripts.spikes.diary_storyboard decide --run ../experiments/diary_storyboard_geo/my-run --expected-revision 5 --choice skip
uv run python -m scripts.spikes.diary_storyboard decide --run ../experiments/diary_storyboard_geo/my-run --expected-revision 5 --choice generate --env-file C:/Users/Administrator/Downloads/forwork/env
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
uv run python -m scripts.spikes.diary_storyboard start --run ../experiments/diary_storyboard_geo/replay --replay-from ../experiments/diary_storyboard_geo/my-run
```

같은 review 입력을 적용하고 decide에 `--replay-from`을 주면 일기도 재생한다.
입력·모델·프롬프트·스키마·앞선 상태가 달라져 요청 지문이 다르면 재생을 거부한다.
수정한 프롬프트를 옛 응답으로 평가하는 용도로 사용하지 않는다.

## 검증과 남은 경계

### 행동 정규화·근거 대조 비교

같은 계산 입력으로 세 번의 초안을 만들고, 각 초안을 두 조건으로 나눈다. 아래 명령의
`--pair`를 1, 2, 3으로 바꿔 **순차 실행**한다. 재개도 동일 명령을 사용한다.

```powershell
uv run python -m scripts.spikes.diary_storyboard.claim_experiment --input ../experiments/diary_storyboard_geo/my-input/evidence.json --root ../experiments/diary_storyboard_geo/my-comparison --pair 1 --env-file C:/Users/Administrator/Downloads/forwork/env
uv run python -m scripts.spikes.diary_storyboard.compare_claim_runs --root ../experiments/diary_storyboard_geo/my-comparison
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
uv run python -m scripts.spikes.diary_storyboard.verify_run --run ../experiments/diary_storyboard_geo/my-run
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
