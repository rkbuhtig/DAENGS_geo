# Hex Cellophane의 보수적 연속 Field 복원

상태: `measurement` — 영구 저장 형식이나 통계 원판을 바꾸지 않고, Cellophane을 사용자 화면에
연속적으로 표시할 수 있는지 검증한 실험이다.

## 질문과 경계

[연속 원 field와 Hex 비교](2026-08-31-continuous-hex-comparison.md)는 같은 canonical Segment를
연속 원 kernel과 raw Hex에 투영했다. 그 결과는 raw Hex가 연속 reference보다 거칠다는 뜻이지,
Hex 원판에서 보수적인 연속 표시를 만들 수 없다는 뜻이 아니다. 빠졌던 세 번째 경로를 추가한다.

```text
canonical Segment → continuous brush raster       A. 평가 reference

canonical Segment → Cellophane
                      ├─ piecewise raster          B. raw Hex 기준선
                      └─ local conservative blend  C. 사용자 표시 후보
```

A는 perfect sensor, `NARROW_STEP`, 4m evaluator raster를 사용한 비교 기준이지 실제 산책의
truth가 아니다. B와 C도 제품 저장 형식이 아니다. 둘 다 기존 Cellophane을 공통 측정 raster에
옮겨 비교하기 위한 일회성 결과다.

이 실험은 결정 #69의 경계를 유지한다.

- 산책별 Cellophane `occupancy`·`peak`가 영구 원판이다.
- canonical Segment와 원좌표는 기존 purge 정책을 따른다.
- 단순화 Trail을 새로 영구 저장하지 않는다.
- 복원 Field를 다시 통계 입력이나 판정 근거로 사용하지 않는다.

## 복원 계약

복원은 최종 `SpatialField.values`를 흐리지 않고 **산책별 Cellophane부터** 수행한다. 그래야 다섯
통계의 분자와 분모가 보존된다.

| metric | 복원 뒤 계산 |
|---|---|
| `total_time` | 산책별 occupancy를 복원한 뒤 합산 |
| `visit_rate` | 산책별 방문 support를 세고 선택 산책 수로 나눔 |
| `conditional_dwell` | 복원 시간 합을 pixel별 방문 산책 수로 나눔 |
| `time_utilization` | 복원 시간 합을 전체 시간으로 정규화 |
| `walk_utilization` | 산책마다 합 1로 만든 뒤 기여 산책을 동일 가중 평균 |

`local_blend`는 source cell 하나의 질량을 같은 활성 Hex 연결요소 안의 가까운 pixel에 compact
smoothstep kernel로 나눈다. 각 source cell의 pixel weight를 다시 합 1로 맞추므로 초 질량을
보존한다. 대상 pixel은 원래 점유 Hex들의 합집합으로 제한하므로 빈 셀이나 다른 공간 섬으로
값이 새지 않는다.

기본 reach `1.75 cell`은 제품 상수가 아니라 calibration 모집단에서 고른 이 실험의 명시적
파라미터다. 최종 수치는 다른 seed의 holdout 모집단에서 낸다. evaluator는 calibration seed를
최종 평가 입력으로 다시 쓰면 실패한다. raw 기준선은 같은 support 안에서 source cell 질량을
그 셀의 pixel에 균등 분배한다. 둘 다 셀 경계에 걸친 pixel 면적 근사 차이를 없애기 위해 source
cell마다 질량을 재정규화한다.

## 평가 지표

50% 영역 IoU 하나를 정확도처럼 읽지 않는다. 다음 영수증을 함께 본다.

- 질량 총량과 normalized L1
- 50·80·95% highest-mass region의 면적 IoU
- reference 질량이 candidate 영역에 들어간 양
- candidate 질량이 reference 영역에 들어간 양
- 영역 경계의 양방향 평균 거리와 p95 거리
- 원래 support 밖 leakage와 누락 pixel
- aggregate support의 연결요소 수
- weight 평가 횟수

`visit_rate`와 `conditional_dwell`은 총질량 보존 대상이 아니므로 common raster에서 pointwise
MAE와 최대 오차를 낸다. `total_time`, `U_time`, `U_walk`만 질량 계열로 비교한다.

## 2026-09-01 calibration 결과

같은 perfect-sensor 30회 산책과 4m evaluator raster를 사용했다. 표의 L1과 50% IoU는
`U_time` 결과다.

| Hex radius | raw L1 | 복원 L1 | raw 50% IoU | 복원 50% IoU | leakage | 복원 질량 오차 |
|---:|---:|---:|---:|---:|---:|---:|
| 4u | 0.316 | **0.078** | 0.581 | **0.859** | 0 px | 0 s |
| 8u | 0.271 | **0.173** | 0.582 | **0.712** | 0 px | 0 s |
| 12u | 0.353 | **0.259** | 0.523 | **0.598** | 0 px | 0 s |

앞선 비교 문서의 8u L1 `0.24`와 여기의 raw L1 `0.271`은 같은 구현값이 아니다. 앞선 수치는
pixel 중심에서 Hex cell density를 읽어 적분했고, 여기서는 source cell 질량을 그 cell support의
pixel에 합 1로 재분배했다. C의 개선량은 이 문서 안의 같은 보수적 rasterization을 거친 B와만
비교한다.

이 모집단에서 8u는 잠정 목표였던 `normalized L1 <= 0.18`, `50% area IoU >= 0.70`을
통과했다. 다만 reach 선택에도 이 모집단을 썼으므로 이 표만으로 통과를 확정하지 않는다.

양방향 cross-mass는 완전히 같은 방향으로 움직이지 않았다. 8u 50% 영역에서 reference 질량의
candidate 영역 내 포착량은 `0.473 → 0.512`로 늘었지만, candidate 질량의 reference 영역 내
포착량은 `0.473 → 0.468`로 조금 줄었다. 복원장이 reference의 고밀도 위치를 더 넓게 회수하는
동시에 일부 질량을 reference 50% 경계 밖에도 재배분했다는 뜻이다. 이 방법을 모든 기준에서
우월하다고 주장하지 않는다.

8u의 50% 경계 p95 거리는 raw와 복원 모두 약 8.94m였다. support 자체를 늘리지 않는 계약상
외곽 경계가 항상 좋아지지는 않는다. 반면 4u는 약 8.94m에서 4m, 12u는 약 24.33m에서
14.42m로 줄었다.

### reach 민감도

같은 8u 입력에서 reach만 바꿨다.

| reach | U_time L1 | 50% area IoU | reference mass in candidate region |
|---:|---:|---:|---:|
| 1.50 cell | 0.194 | 0.658 | 0.499 |
| **1.75 cell** | **0.173** | **0.712** | 0.512 |
| 2.00 cell | 0.184 | 0.692 | 0.515 |
| 2.25 cell | 0.193 | 0.671 | 0.519 |
| 2.50 cell | 0.205 | 0.645 | 0.520 |
| 3.00 cell | 0.231 | 0.595 | 0.521 |

reach가 커질수록 reference 질량을 더 많이 덮지만 분포 모양과 50% 경계는 다시 무뎌진다.
1.75 cell은 이 fixture의 L1과 영역 IoU가 함께 가장 좋았던 값이다. 실제 센서 변형에서도 같은
순위인지 확인하기 전에는 제품 상수로 승격하지 않는다.

## 분리된 holdout 결과

reach 선택에 쓰지 않은 다른 모집단 seed에서 `1.75 cell`을 그대로 평가했다.

| Hex radius | raw L1 | 복원 L1 | raw 50% IoU | 복원 50% IoU | leakage | 복원 질량 오차 |
|---:|---:|---:|---:|---:|---:|---:|
| 4u | 0.316 | **0.078** | 0.586 | **0.849** | 0 px | 0 s |
| 8u | 0.271 | **0.173** | 0.578 | **0.707** | 0 px | 0 s |
| 12u | 0.353 | **0.260** | 0.521 | **0.603** | 0 px | < 4e-12 s |

8u는 holdout에서도 `normalized L1 <= 0.18`, `50% area IoU >= 0.70`을 통과했다. 질량
손실, support 누출, support 연결요소 변화도 없었다. 따라서 raw Hex의 계단 모양만 보고 영구
Trail이 필요하다고 결론 내릴 근거는 더 약해졌다. 다만 경로군 구성 자체는 같고 날짜·행동
변형만 분리한 첫 holdout이므로, 다음 단계의 센서 변형과 새 경로군 검증을 대신하지 않는다.

## 재현

```bash
uv run python -m scripts.spikes.territory_paint.conservative_hex_evaluation \
  --out conservative-hex-evaluation.json \
  --pixel-m 4 \
  --blend-reach-cells 1.75
```

JSON은 A/B/C의 다섯 통계, 50·80·95% 양방향 질량 포착, 경계 거리, support·질량·연결성
영수증을 담는다. 계산 시간은 환경에 따라 달라지므로 파일에 싣지 않고 CLI에서만 출력한다.

## 다음 단계

수치상으로는 C를 실제 지도에 올려 볼 근거가 생겼다. 다음 PR에서는 A/B/C가 동일한 viewport,
색상, 고정 exposure를 쓰게 하고 raw Hex 경계는 개발자 검산으로만 노출한다. 화면 평가가 끝날
때까지 이 복원기는 `scripts/spikes` 밖으로 승격하지 않는다.
