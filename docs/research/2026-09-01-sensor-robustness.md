# GPS 오염에서 Cellophane과 보수적 Field가 어디서 무너지는가

## 질문

[보수적 연속 Field 복원](2026-09-01-conservative-hex-reconstruction.md)에서 선택한 `8u`와
`1.75 cell`을 다시 튜닝하지 않고 실제 휴대폰형 GPS 실패에 통과시키면 무엇이 달라지는가?

이 실험은 하나의 최종 오차만 내지 않는다.

```text
같은 latent 산책
├─ perfect sensor → canonical Segment → continuous reference
└─ noisy sensor
   → 기존 compute_facts
   → canonical Segment
   → Cellophane 8u
   → local_blend 1.75 cell
```

센서가 만든 손실과 Hex projection이 만든 손실을 섞지 않기 위해 다음 세 비교를 함께 낸다.

- `sensor_only_continuous`: perfect continuous와 noisy continuous
- `projection_given_sensor`: noisy continuous와 noisy Cellophane 복원
- `combined_against_perfect`: perfect continuous와 noisy Cellophane 복원

continuous reference도 perfect GPS와 고정 붓으로 만든 평가 기준이지 실제 위치 truth는 아니다.
결과는 제품 임계값이나 자동 보정 근거가 아니다.

## 고정 계약

- 모집단: reach calibration·첫 holdout과 다른 결정론적 30회 `sensor_holdout`
- sampling: 5초
- Hex radius: `8u`
- reconstruction reach: `1.75 cell`
- evaluator raster: 4m
- reach 재튜닝: 없음
- exposure 재튜닝: 없음

센서 profile은 fingerprint와 명시적 replay seed를 함께 남기되 latent branch·hold label은 싣지
않는다. 난수는 stable walk key와 sample index에 현상 이름을 더한 독립 stream을 쓴다. 따라서
dropout 강도만 올리면 먼저 빠졌던 fix는 그대로 빠지고, jitter를 켜도 outlier·accuracy 사건
위치는 바뀌지 않는다.

## 센서 시나리오

| 이름 | 주입한 현상 |
|---|---|
| `clean_control` | noisy 관측 경로를 사용하지만 오염은 0 |
| `jitter` | 좌표 축별 Gaussian 4m, accuracy 표준편차 2m |
| `dropout` | 시작·끝을 제외한 fix 12% 누락 |
| `outlier` | fix 0.8%를 260m 이동 |
| `drift` | 산책 종료까지 동쪽 18m·남쪽 10m로 선형 이동 |
| `variable_accuracy` | accuracy 표준편차 6m, fix 8%를 80m accuracy로 표시 |
| `combined` | jitter 3m, dropout 8%, outlier 0.4%, drift 12m/−6m, 낮은 accuracy 5% |

outlier와 낮은 accuracy는 센서 모델이 제거하지 않는다. 제품의 현재 `compute_facts`가 각각
`MAX_JUMP_M=200m`, `MAX_ACCURACY_M=50m` 계약으로 처리한다.

## 단계별 영수증

- 수집·canonical: fix 보존율, 인정 시간, 거리 비율, accuracy 거부·jump·gap 횟수와 산책별 분포
- Cellophane: canonical 인정 시간과 paint 질량 차이, perfect 대비 support IoU·누락·누출의
  모집단 합집합과 산책별 min·p10·p50·mean·p90·max
- Field: sensor-only·projection-only·combined 각각의 다섯 metric, 50·80·95% 질량 영역 IoU와
  경계 거리
- hard invariant: 산책별 Cellophane·복원 질량 보존과 복원 support 무누출·무누락

soft metric은 관찰값이다. 이번 결과를 보고 사후 합격선을 만들지 않는다.

## 30회 결과

아래 L1과 50% IoU는 `combined_against_perfect`의 `U_time`이다.

| scenario | fix 보존 | 인정 시간 | sensor L1 | sensor 50% IoU | combined L1 | combined 50% IoU |
|---|---:|---:|---:|---:|---:|---:|
| clean control | 1.000 | 1.000 | 0.000 | 1.000 | 0.173 | 0.706 |
| jitter | 1.000 | 1.000 | 0.125 | 0.807 | 0.188 | 0.676 |
| dropout | 0.880 | 1.000 | 0.006 | 0.990 | 0.173 | 0.705 |
| outlier | 1.000 | 0.981 | 0.017 | 0.954 | 0.174 | 0.698 |
| drift | 1.000 | 1.000 | 0.575 | 0.361 | 0.568 | 0.363 |
| variable accuracy | 1.000 | 0.828 | 0.061 | 0.850 | 0.189 | 0.654 |
| combined | 0.920 | 0.893 | 0.415 | 0.492 | 0.414 | 0.486 |

| scenario | 모집단 Cell IoU | 산책별 최저 Cell IoU | 인정 시간 p10 | jump break | accuracy 거부 |
|---|---:|---:|---:|---:|---:|
| clean control | 1.000 | 1.000 | 1.000 | 0 | 0 |
| jitter | 0.830 | 0.774 | 1.000 | 0 | 0 |
| dropout | 1.000 | 0.991 | 1.000 | 0 | 0 |
| outlier | 1.000 | 0.996 | 0.953 | 74 | 0 |
| drift | 0.773 | 0.662 | 1.000 | 0 | 0 |
| variable accuracy | 0.998 | 0.984 | 0.749 | 0 | 357 |
| combined | 0.819 | 0.735 | 0.838 | 29 | 188 |

모든 시나리오의 모든 산책에서 hard invariant는 통과했다. 모집단 합집합만 보면 dropout과
outlier support IoU가 1에 가깝지만 산책별 영수증에서는 작은 누락과 인정 시간 하락이 드러난다.

## 해석

### 1. dropout과 큰 단발 outlier는 현재 canonical 계약이 잘 흡수한다

5초 sampling에서 12% dropout은 대부분 60초 gap 문턱 안에서 앞뒤 fix가 다시 이어져 인정
시간과 분포가 거의 유지됐다. 260m outlier는 jump break로 끊겨 combined 분포를 조금만 바꾸고
않았다. 이것은 모든 dropout·outlier가 안전하다는 뜻이 아니라 이번 강도에서 현재 필터가
의도대로 작동했다는 뜻이다.

### 2. accuracy 거부는 위치 누출보다 시간 손실을 만든다

80m accuracy fix 자체는 Cellophane에 칠해지지 않았지만, 거부점 양쪽 segment도 연결하지 않기
때문에 인정 시간이 82.8%, 산책별 p10은 74.9%로 줄었다. support 모양은 거의 유지돼도
visit/dwell 강도가 약해질 수
있다. UI가 이를 실제 이용 감소로 설명하면 안 된다.

### 3. drift는 현재 가장 큰 실패 축이다

drift의 sensor-only L1 `0.575`와 combined L1 `0.568`은 거의 같다. 즉 Hex 복원이 새로 만든
오류보다 센서 관측 자체가 field를 이동시킨 영향이 압도적이다. 복원 reach를 다시 조정해 해결할
문제가 아니다. combined도 같은 이유로 크게 나빠졌다.

### 4. 복원기는 구조적으로 보수적이지만 위치 정확도를 보장하지 않는다

모든 profile에서 질량과 source support 제약은 지켰다. 따라서 `1.75 cell` 복원은 noisy
Cellophane을 추가로 새게 하거나 빈 공간을 잇지는 않는다. 그러나 입력 Cellophane 자체가 drift로
이동하면 그 잘못된 support 안에서 정직하게 복원할 뿐이다.

## 재현

```bash
uv run python -m scripts.spikes.territory_paint.sensor_robustness_evaluation \
  --out sensor-robustness-evaluation.json

# 빠른 한 시나리오 검산
uv run python -m scripts.spikes.territory_paint.sensor_robustness_evaluation \
  --scenario drift \
  --walk-limit 3 \
  --out sensor-drift-smoke.json
```

## 결론과 다음 단계

- Cellophane 질량 보존과 보수적 복원 support 계약은 센서 오염에서도 유지됐다.
- `1.75 cell`을 센서 오류 보정값으로 해석하면 안 된다.
- 다음 실제 지도 화면은 projection 비교보다 `perfect ↔ noisy` 전환을 우선해야 한다.
- 실제 기기에서 drift·accuracy 시계열을 수집해 합성 강도가 현실적인지 먼저 보정해야 한다.
- 통계 화면에는 관측 손실 또는 위치 불확실성을 별도 evidence로 노출할 방법이 필요하다.
