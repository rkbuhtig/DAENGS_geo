# Cellophane GeoJSON 계약

`app/features/territory/geojson.py`가 만드는 순수 출력 계약이다. 현재는 검증 화면과 후속 API가
공유할 내부 계약이며 DB 저장이나 HTTP 경로를 정하지 않는다.

## 입력

- Paint v2 `Cellophane` 한 장
- 그 장을 만든 canonical `Segment[]`

Segment는 `compute_facts()`가 연속성 경계를 적용한 뒤의 유효 구간이어야 한다. serializer는
raw fix를 다시 판정하거나 경계 사이를 보간하지 않는다.

## 출력

최상단은 GeoJSON `FeatureCollection`이고 `meta`를 foreign member로 함께 둔다.

```json
{
  "type": "FeatureCollection",
  "meta": {
    "cellophane_geojson_version": 2,
    "walk_calculation_version": 4,
    "moving_speed_threshold_mps": 0.5,
    "slow_candidate_speed_threshold_mps": 1.0,
    "session_id": "walk-1",
    "paint_version": 2,
    "paint_fp": "…",
    "grid_version": "hex-v1",
    "radius_u": 8.0,
    "profile_name": "계단 3·8·20",
    "profile_fp": "…",
    "sample_step_m": 1.5,
    "source_segment_s": 842.5,
    "occupancy_mass_s": 842.5,
    "mass_error_s": 0.0,
    "mass_conserved": true,
    "segment_count": 60,
    "chain_count": 2,
    "cell_count": 73
  },
  "features": []
}
```

Feature는 두 종류다.

- `properties.kind == "accepted_chain"`: continuity chain 하나당 `LineString` 하나. 속성은
  `chain_index`, `segment_count`, `source_segment_s`와 `segment_duration_s`,
  `segment_distance_m`, `segment_speed_mps`, `segment_moving` 배열을 가진다. 네 배열의 index는
  LineString의 같은 index 좌표에서 다음 좌표로 가는 edge와 일치한다. `speed_mps`는 GPS가
  직접 보고한 값이 아니라 canonical Segment의 `dist / dt` 파생값이다.
- `properties.kind == "cell"`: 셀 하나당 서버가 계산한 정육각 `Polygon` 하나. 속성은
  `cell_id`, `q`, `r`, `occupancy_s`, `peak`를 가진다.

## 불변식

1. LineString은 `chain_index` 순, Polygon은 `(q, r)` 순이다. canonical JSON은 key도 정렬한다.
2. GeoJSON 좌표는 `[lng, lat]`이고 Polygon ring은 첫 좌표를 끝에 반복해 닫는다.
3. 같은 chain의 Segment 끝점이 실제로 이어지지 않으면 직선을 만들지 않고 실패한다.
4. `cell_id`는 `{grid_version}:{radius_u}:{q}:{r}`다. 이는 **공간 동일성**이며 Paint 계산
   동일성인 `paint_fp`와 분리한다.
5. `occupancy_s`는 실제 육각형 내부 체류가 아니라 그 셀에 kernel로 배분된 관측 시간(초)이다.
6. `mass_error_s = occupancy_mass_s - source_segment_s`이며 반올림하지 않는다.
7. `occupancy`와 `peak`의 셀 집합이 다르거나 값이 유한한 계약 범위를 벗어나면 실패한다.
8. chain의 segment 배열 네 개는 모두 `segment_count == coordinates.length - 1` 길이다.
   `duration_s`는 유한한 양수, `distance_m`와 파생 `speed_mps`는 유한한 0 이상이다.
9. `segment_moving`은 `walk_calculation_version`의 canonical 판정이다. viewer는 정지 여부를
   속도에서 다시 추론하지 않는다. 저속 후보 표시는 payload의 두 threshold를 사용한다.

색상, opacity, 범례, hover 상태는 이 계약에 없다. 그것들은 지도를 그리는 소비자의 표현이다.
