---
status: exploring
implementation: working-skeleton
---
# 결정론적 산책 시뮬레이터 core

`scripts/verify/walk_fixture.py`는 정확한 계약 검사용이다. 고정 직선·고정 속도·정지 1회라는
단순함 덕분에 encounter 예상값을 손으로 검증할 수 있으므로 무작위로 바꾸지 않는다.

산책스러운 변화와 현재 판정기의 실패를 탐색하는 입력은 `scripts/sim/walk`가 별도로 만든다.

```text
BehaviorPlan       지도와 독립된 v(s), slow motif, hold, fatigue
    ↓ dt/ds 적분
MotionTruth        시간축 progress와 실제 로컬 east/north 동선
    ↓ RouteGeometry의 호 길이 투영
Sensor             Perfect(고정 간격) | Noisy(seed 기반 GPS 오염)
    ↓ 명시적 시간축 fault
Trace              같은 sample ID의 truth ↔ observed 대응
    ↓ 독립 delivery 계획
Delivery           앱 도착 지연·배치·역순·중복
    ↓ 기존 production 순수함수
compute_facts → observations → paint_sheet → Cellophane GeoJSON
    ↓ 같은 motion의 Perfect 기준군과 짝 비교
Evaluation         Sensor → CanonicalTrail → Cellophane → Delivery 영수증
```

## 진실의 층

- `latent_state`는 생성 원인이지 제품 판정의 정답이 아니다.
- `target_speed_mps`는 행동 테이프가 요구한 연속 속도장 `v(s)`다.
- `forward_speed_mps`는 적분된 진행거리의 실제 시간 변화율이다.
- 첫 버전에는 횡이동이 없으므로 `ground_speed_mps`와 forward speed가 같다.
- `WalkFix`에는 속도를 넣지 않는다. 제품과 똑같이 연속 GPS 점의 거리와 시간으로 계산한다.
- 짙기를 입력으로 만들지 않는다. 기존 Paint가 관측된 segment 시간을 셀에 분배한다.
- 모든 fix는 `is_mock=true`다.

`SlowMotif`는 cosine envelope로 진입·유지·회복을 부드럽게 만든다. preset의 seed는 motif
위치·폭·깊이를 제한적으로 흔들지만, 실제 산책 분포를 안다고 주장하지 않는다. 확률적 GPS
오염은 `NoisySensor`, 사람이 특정 시점에 심는 결함은 `faults`, 센서가 캡처한 뒤 앱에 도착하는
문제는 `delivery`가 맡는다. 셋을 섞지 않으므로 같은 truth에서 한 축만 바꿔 비교할 수 있다.

## 실행

```powershell
uv run python -m scripts.sim.walk.cli `
  --behavior exploratory `
  --route s-curve `
  --length-m 600 `
  --seed 48123 `
  --chain-break-m 360 `
  --out C:/dev/walk-sim/exploratory-48123
```

`--behavior`은 `steady`, `exploratory`, `fatigued`, `stop-heavy`를, `--route`는 `straight`,
`s-curve`, `loop`, `out-and-back`을 받는다. 출력 폴더가 비어 있지 않으면 기존 실행을 덮지
않고 실패한다. 기본 session ID는 generator version과 behavior, route, seed, sampling,
chain break, 시작 시각·원점 등 관측 결과를 바꾸는 입력 전체에서 결정론적으로 만든다. 외부
실행명과 맞춰야 할 때만 `--session-id`로 명시한다.

지도에서 그린 임의 polyline과 세부 행동·결함은 versioned JSON으로 저장한 뒤 다시 실행한다.

```powershell
uv run python -m scripts.sim.walk.cli `
  --spec scripts/sim/walk/examples/sniff-and-go.json `
  --out C:/dev/walk-sim/authored-result
```

`walk-trace-scenario-v1`은 다음 네 경계를 가진다.

- `route.points_xy`: 원점 기준 east/north 미터 polyline
- `motion`: 기준 속도, 거리축 slow motif, hold, fatigue
- `sensor`: perfect/noisy 표본화와 확률 오염
- `faults` / `delivery`: 의도한 GPS 결함과 앱 전달 결함

명시적 센서 fault는 시간 구간 dropout, 시간 구간 accuracy 저하, 한 표본 position offset을
지원한다. delivery는 기본 지연, 시간 구간 추가 지연, batch, batch 내부 역순, 특정 캡처 시각의
중복 전달을 지원한다. 시나리오에 session ID가 없으면 **시나리오 전체 내용**에서 안정적인 ID를
만든다.

```text
scenario.json       재실행 가능한 walk-trace-scenario-v1 입력
manifest.json       generator version, seed, 최종 motif, route, sensor/fault 계약
truth.json          GPS 이전의 1초 간격 실제 운동
walk-export.json    Android export와 같은 서버 입력 계약
trace.json          sensor 간격별 truth ↔ observed sample 대응과 fault 표식
delivery.json       capture와 분리된 앱 도착 순서·지연·batch·duplicate
derived.json        facts, curve, 관측, 구간별 파생 속도
cellophane.geojson  기존 canonical Paint 결과
evaluation.json     같은 motion의 Perfect 기준군 대비 층별 정량 영수증
```

같은 scenario는 위 아홉 출력을 다시 만든다. delivery만 바꾸면 `walk-export`와 canonical
계산값은 그대로이고 도착 사건만 바뀐다. sensor/fault만 바꾸면 truth는 그대로이고 관측부터
달라진다. 이 분리가 이후 Android replay source와 서버 업로드 adapter의 기준선이다.

`evaluation.json`은 같은 route·motion·표본 간격을 Perfect 센서/무결함/중립 delivery로 다시
실행한 기준군과 후보군을 짝 비교한다. Sensor의 fix 보존율·위치 오차·명시적 fault 귀속,
CanonicalTrail의 truth 거리/시간 오차와 hold 중 거짓 거리, Cellophane support IoU·누락/누출
셀·질량 보존, Delivery의 지연·역순·중복·sample ID 정합성을 한 영수증에 남긴다. 수치 metric은
관찰값이며 사후 제품 합격선으로 만들지 않는다. pass/fail은 유한값, 질량 보존, delivery 참조
정합성과 delivery가 캡처/canonical을 바꾸지 않는다는 명백한 불변식에만 둔다.

## 지도 저작 Lab

CLI 계약을 바꾸지 않고 `dev_console` 뒤에서 시나리오를 지도에 그려 실행할 수 있다.

```powershell
$env:DAENGS_DEV_CONSOLE="true"
uv run uvicorn app.main:app --reload
# http://127.0.0.1:8000/walk-trace-lab
```

화면은 한 번의 요청에서만 계산하고 서버 파일이나 DB를 쓰지 않는다. 지도 클릭 경로를 첫 점
기준 east/north 미터로 바꾸고, 움직임·센서·명시적 fault·delivery를 조립해 PR 1의 동일한
`build_scenario_from_spec()`을 호출한다. 결과 지도는 truth와 GPS 관측, canonical Cellophane을
겹치고 아래 시간축은 누락·정확도 저하·좌표 튐과 전달 사건을 같은 `sample_id`로 읽는다.
지도 아래 Perfect 비교 영수증은 네 층의 손실을 나란히 보여 주되 soft metric을 색으로
합격/불합격 판정하지 않는다.

예제나 불러온 JSON은 원 계약 그대로 먼저 실행한다. 화면 값을 바꾼 뒤 재실행하면 UI가
지원하는 명시적 항목으로 새 계약을 만들며, 자동 저장하지 않는다. `JSON 저장`으로 얻은 파일은
다시 CLI `--spec` 또는 Lab 입력으로 쓸 수 있다. 이 표면은 Android replay나 제품 Spatial
Diary UI가 아니다.

## 셀로판 모집단 fixture

단일 산책의 싸인펜 검증과 여러 산책의 z축 검증을 섞지 않도록 30회 모집단은 별도 builder가
만든다.

```python
from scripts.sim.walk.population import observe_population
from scripts.sim.walk.population_truth import build_population_truth

truth = build_population_truth()       # evaluator만 보관
observation = observe_population(truth)
sheets = observation.sheets            # 통계 계산기에 전달할 유일한 입력
```

모든 산책은 같은 집과 공통 현관·주 동선에서 시작해 다시 집으로 돌아온다. 생성 비율은 동쪽
루프 14회, 남쪽 왕복 9회, 북쪽 공원 4회, 임시 탐색 3회다. 북쪽 공원에만 180초 이상의 긴
체류를 심는다. `PopulationObservation`에는 이 branch와 hold label, 원래 seed가 없고 관측
GPS·canonical Segment·Cellophane만 남는다. 통계층은 `sheets`만 읽으며, branch별 기대
순위와 질량 영역 회수는 evaluator가 truth를 사후 결합하는 다음 단계에서 검증한다.

통계 지도 fixture와 dev 화면:

```powershell
uv run python -m scripts.spikes.territory_paint.population_distribution `
  --out cellophane-distribution.json
$env:DAENGS_DEV_CONSOLE="true"
uv run uvicorn app.main:app --reload
# http://127.0.0.1:8000/cellophane-distribution
```

화면 payload에는 branch·hold·seed가 없고 다섯 `SpatialField`의 값과 영수증, `U_time`·
`U_walk`의 50·80·95% 외곽선만 있다. 대신 실험 재현에 필요한 모집단 generator version·
run ID와 Paint 세대는 보존한다. Naver가 설정됐지만 현재 localhost 출처가 허용되지 않거나
provider가 다르면 설정의 `fallback=osm`에 따라 OpenStreetMap 실지도로 전환한다.

육각 격자 자체가 결과를 얼마나 바꾸는지는 같은 canonical Segment를 grid-free reference로
읽는 `continuous_brush_field()`와 비교한다. 이 reference는 원형 kernel의 면적 적분을 1로
정규화해 입력 `Σ Segment.dt`를 보존하며, 아직 저장·API·제품 renderer에 사용하지 않는다.
계약과 다음 비교 항목은
[`continuous-brush-reference.md`](./continuous-brush-reference.md)에 고정한다.
