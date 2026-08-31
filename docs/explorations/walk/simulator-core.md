# 결정론적 산책 시뮬레이터 core

`scripts/verify/walk_fixture.py`는 정확한 계약 검사용이다. 고정 직선·고정 속도·정지 1회라는
단순함 덕분에 encounter 예상값을 손으로 검증할 수 있으므로 무작위로 바꾸지 않는다.

산책스러운 변화와 현재 판정기의 실패를 탐색하는 입력은 `scripts/sim/walk`가 별도로 만든다.

```text
BehaviorPlan       지도와 독립된 v(s), slow motif, hold, fatigue
    ↓ dt/ds 적분
MotionTruth        시간축 progress와 실제 로컬 east/north 동선
    ↓ RouteGeometry의 호 길이 투영
PerfectSensor      고정 간격의 mock WalkFix와 명시적 chain break
    ↓ 기존 production 순수함수
compute_facts → observations → paint_sheet → Cellophane GeoJSON
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
위치·폭·깊이를 제한적으로 흔들지만, 실제 산책 분포를 안다고 주장하지 않는다. GPS drift,
dropout, outlier도 아직 없다. 먼저 perfect observation에서 truth와 canonical 연결을 고정한
뒤 별도 sensor version으로 추가한다.

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

```text
manifest.json       generator version, seed, 최종 motif, route, sensor 계약
truth.json          GPS 이전의 1초 간격 실제 운동
walk-export.json    Android export와 같은 서버 입력 계약
derived.json        facts, curve, 관측, 구간별 파생 속도
cellophane.geojson  기존 canonical Paint 결과
```

같은 seed는 위 다섯 출력을 다시 만들 수 있다. behavior는 그대로 두고 route만 바꾸면 실제
동선 모양만, sensor seed를 추가할 다음 단계에서는 observation만 바꿔 원인을 분리한다.

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
GPS·canonical Segment·Cellophane만 남는다. PR1 통계층은 `sheets`만 읽으며, branch별 기대
순위와 질량 영역 회수는 evaluator가 truth를 사후 결합하는 다음 단계에서 검증한다.
