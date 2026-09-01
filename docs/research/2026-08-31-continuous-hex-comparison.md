# 연속 원 field와 Hex Cellophane 비교

상태: `measurement` — 저장 형식 승격 결정이 아니라 같은 canonical 산책을 두 투영에 넣은
수치 비교다.

## 질문

Hex는 좌표 purge 뒤 공간 질문을 가능하게 하는 손실 압축이다. 그렇다면 육각형이 연속
싸인펜 자국을 얼마나 왜곡하는가? 이 문서는 같은 30회 canonical `Segment`를 다음 두 경로로
보내 답한다.

```text
canonical Segment
├─ ContinuousBrushField → 4m 정사각 측정 raster
└─ paint_sheet()        → Hex Cellophane 4u / 8u / 12u
```

4m 정사각 raster는 제품 격자나 저장 후보가 아니다. grid-free field의 원 kernel을 수치 적분하고
Hex 값을 같은 위치에서 읽기 위한 evaluator-only 측정 종이다. 각 dab의 raster weight는 합 1로
정규화해 시간 질량을 보존하고, 정규화 전 적분 오차도 별도로 기록한다.

## 비교 계약

- 입력: 동일한 perfect-sensor 30회 관측에서 나온 canonical `Segment`
- 붓: `NARROW_STEP` 3·8·20m
- 연속 표본 간격: profile 심의 절반인 1.5m
- Hex 반지름: 4·8·12 **격자 단위(u)**. 서울 위도에서 실제 지상 반지름은 약
  3.17·6.35·9.52m다.
- 통계: `total_time`, `visit_rate`, `conditional_dwell`, `time_utilization`,
  `walk_utilization`
- 영역: time/walk utilization의 상위 질량 50·80·95%
- 민감도: perfect sensor의 1·5·10초 수집 간격

초·share 계열은 각 값을 면적으로 나눈 밀도로 공통 raster에서 적분한다. 방문률은 무차원이라
pixel 중심에서 직접 비교한다. 질량 영역은 Hex cell 집합을 공통 raster에 투영한 뒤 면적 IoU를
구한다.

## 2026-08-31 기준 결과

30회 source Segment 시간은 19,797.321518초다. 연속 raster와 세 Hex 반지름 모두 이 질량을
부동소수 오차 범위에서 보존했다. 4m raster의 정규화 전 kernel 적분비는 1.0114로, 측정 해상도
때문에 생기는 오차가 약 1.1%임을 영수증에 남겼다.

| Hex radius | 실제 지상 반지름 | support IoU | U_time 정규화 L1 | U_time 50% 영역 IoU | U_time 95% 영역 IoU |
|---:|---:|---:|---:|---:|---:|
| 4u | 3.17m | 0.95 | 0.13 | 0.79 | 0.90 |
| 8u | 6.35m | 0.91 | 0.24 | 0.60 | 0.83 |
| 12u | 9.52m | 0.86 | 0.35 | 0.53 | 0.76 |

격자가 거칠어질수록 support와 **상위 50% 질량으로 자른 영역의 경계**가 연속 reference에서
멀어진다는 예상이 이 임계값 아래에서 확인됐다. 이 IoU를 경로 정확도로 읽을 수는 없다. 다만
세 반지름 모두 support 총면적은 reference의 약 0.99~1.00배이고 시간 질량도
보존한다. 즉 지금 측정된 차이는 “시간이 사라짐”보다 “같은 시간을 어느 공간에 배분했는가”의
차이다.

1·5·10초 perfect-sensor 실험은 30회 모두 같은 accepted 시간을 보존했고, 10초와 5초의
`U_time` L1 차이는 약 0.01이었다. 이 결과는 완벽한 센서의 수집 간격만 다룬다. dropout,
drift, outlier, 가변 accuracy는 현재 센서 fixture 계약에 존재하지 않으므로 임의의 노이즈를
심지 않고 후속 실험으로 명시했다.

서로 다른 continuity chain의 정지점 두 개를 120m 떨어뜨린 별도 probe에서는 연속장과 모든
Hex 반지름의 중간점 값이 0이었다. 두 투영 모두 입력에 없는 gap 선을 만들지 않는다.

## 재현

```bash
uv run python -m scripts.spikes.territory_paint.continuous_hex_comparison \
  --out continuous-hex-comparison.json
```

JSON에는 계산 시간 대신 결정론적인 dab 수, stamp 평가 수, pixel/cell 수를 싣는다. 벽시계
시간은 실행 환경에 따라 달라지므로 CLI 완료 메시지에서만 보고한다.

## 실제 지도 비교 화면

현재 개발자 화면은 A 연속 reference, B raw Hex, C 보수적 복원 Field를 실제 Naver/OSM 지도
위에서 전환한다.

```bash
uv run python -m scripts.spikes.territory_paint.continuous_hex_visualization \
  --out continuous-hex-visualization.json
DAENGS_DEV_CONSOLE=true uv run uvicorn app.main:app --reload
# http://127.0.0.1:8000/continuous-hex-comparison
```

기본 화면은 `U_time`의 A 연속 기준이다. `A / B / C / A+C 겹침`, 다섯 metric,
4·8·12u, 50·80·95% 영역을 바꿀 수 있다. Hex 경계는 기본적으로 숨기고 검산 버튼으로만
드러낸다. 지도 클릭은 같은 위치의 A/B/C 값과 면적밀도 차이를 함께 보여 준다.

A와 C는 Naver HeatMap으로 다시 흐리지 않는다. 서버에서 계산한 4m 측정 raster를 투명
이미지로 만들고 bilinear 표시만 적용한다. 세 표현은 화면별 최댓값이 아닌 metric별 고정
면적밀도 exposure를 공유하므로 mode 전환 뒤에도 색의 의미가 바뀌지 않는다.

## 현재 판단

이 실험만으로 Hex를 버릴 근거는 없다. 4u는 연속 reference에 꽤 가깝지만 cell 수가 8u의 약
4배라 payload와 저장 비용이 커진다. 8u는 비용과 왜곡의 중간점이고, 12u는 상위 질량 영역 경계가
눈에 띄게 무뎌진다. 저장/purge 결정을 바꾸기 전에 실제 센서 변형과 실기기 산책에서도 같은
곡선이 유지되는지 확인해야 한다.

raw Hex와 reference 사이에 빠졌던 사용자 표시 후보는
[Hex Cellophane의 보수적 연속 Field 복원](2026-09-01-conservative-hex-reconstruction.md)에서
별도로 비교한다.
