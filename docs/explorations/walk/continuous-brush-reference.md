# Continuous Brush Reference

상태: `exploring` — Hex Cellophane의 대체 저장 형식이 아니라 비교 기준 계산기다.

## 질문

산책을 반경이 있는 원의 연속적인 덧칠로 직접 읽으면, 육각 격자에 투영한 현재
Cellophane과 어디서 얼마나 달라지는가?

이 질문에 답하기 전에 제품 화면을 먼저 만들거나 육각형을 제거하지 않는다. 동일한 canonical
Segment를 두 방식에 넣을 수 있는 독립 기준선을 먼저 만든다.

```text
canonical Segment
├─ continuous_brush_field() → 연속 원 kernel field
└─ paint_sheet()            → Hex Cellophane
```

## 입력 경계

입력은 raw fix가 아니라 `compute_facts()`가 수용한 canonical `Segment`다.

- 시간 역행, 낮은 정확도, jump는 이미 거부됐다.
- pause와 gap은 continuity chain을 끊었다.
- chain 사이를 새 Segment로 연결하지 않는다.
- `accuracy_m`는 관측 불확실성이며 `BrushProfile`의 영역 반경과 합치지 않는다.

따라서 reference가 새로 GPS 품질을 판정하거나 누락 구간을 추정하지 않는다.

## 연속 field

Segment를 `sample_step_m` 이하의 조각으로 나누고 각 중점에 시간 질량 원 `BrushDab`을 둔다.

```text
BrushDab
- lat / lng
- mass_s
- chain_index
```

Segment `s`를 `n`개로 나누면 각 dab 질량은 `s.dt / n`이다. 원형 kernel `K`는
`BrushProfile.weight_at(distance)`를 면적 적분값으로 나눠 다음을 만족한다.

```text
∫ K(x) dx = 1
∫ mass_s · K(x) dx = mass_s
```

한 산책의 연속 시간 밀도는 다음이다.

```text
F(x) = Σ_dab mass_s(dab) · K(distance(x, dab))
```

단위는 `s/m²`다. 겹치는 경로·저속·정지는 같은 위치의 density를 선형으로 높인다.
`peak_at(x)`는 시간 합이 아니라 가장 가까운 dab의 raw kernel 세기 최댓값이라 왕복 횟수나
체류 시간이 늘어도 부풀지 않는다.

## 계산 세대

`ContinuousBrushSpec`은 다음으로 지문을 만든다.

- continuous brush version
- `BrushProfile` fingerprint
- resolved `sample_step_m`

격자를 사용하지 않으므로 `grid_version`과 `radius_u`는 없다. profile의 표시 이름도 계산
동일성에는 들어가지 않는다.

## PR A 불변식

1. field의 해석적 총질량은 입력 Segment의 `Σdt`와 같다.
2. 같은 경로를 다시 지나면 density는 더해지고 peak 의미는 바뀌지 않는다.
3. 같은 시간·경로를 다른 Segment 간격으로 표현해도 field가 허용오차 안에서 같다.
4. 서로 다른 continuity chain 사이에 새로운 붓 이동을 만들지 않는다.
5. profile이나 sample step이 바뀌면 reference fingerprint가 바뀐다.
6. 코드 어디에도 육각 셀·grid radius·셀 ID가 입력되지 않는다.

## 의도적으로 하지 않는 것

- DB 저장 또는 API 제공
- Hex Cellophane 교체
- 여러 산책의 다섯 통계 재구현
- raster/tile 생성
- 지도 renderer
- GPS accuracy-aware kernel
- 50·80·95% 연속 질량 영역

canonical Segment는 원좌표 purge 전까지만 재생성 가능하다. 따라서 이 reference가 향후 더 좋은
결과를 보여도 저장·purge 결정을 별도 설계 없이 바꾸지 않는다. 현재 Cellophane은 purge 후 남는
영구 공간 측정값이라는 기존 계약을 유지한다.

## 다음 비교 PR

같은 30회 fixture와 센서 변형을 두 projection에 넣고 다음을 측정한다.

- 총질량 오차
- 위치별 density 차이
- 방문률·체류·`U_time`·`U_walk`의 차이
- 50·80·95% 영역 겹침률
- 육각 해상도 민감도
- gap의 가짜 연결 여부
- 계산 시간과 payload 크기

그 결과가 나오기 전까지 “육각형 유지”와 “연속 field로 교체” 중 어느 쪽도 제품 결정으로
승격하지 않는다.
