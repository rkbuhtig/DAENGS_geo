"""셀로판 한 장과 그 원천 Segment를 결정론적 GeoJSON으로 직렬화한다. 순수함수.

이 모듈은 저장·HTTP·지도 SDK를 모른다. Paint가 만든 한 장을 검증 화면이나 후속 API가
같은 형태로 읽게 하는 경계다.

끊긴 경로를 단일 LineString으로 만들지 않는다. continuity chain 하나가 Feature 하나이며,
같은 chain 안의 Segment조차 실제 끝점이 이어지지 않으면 오류로 멈춘다. serializer가 없던
이동을 직선으로 보간하는 것보다 입력 계약이 깨졌다고 드러내는 편이 안전하다.
"""

import json
import math
from collections import defaultdict
from collections.abc import Iterable
from itertools import pairwise

from app.features.territory.paint import Cellophane
from app.features.walk.facts import Segment
from app.features.walk.models import WalkFix
from app.geo.cells import GRID_VERSION, Cell, hex_boundary_latlng

CELLOPHANE_GEOJSON_VERSION = 2


def spatial_cell_id(grid_version: str, radius_u: float, cell: Cell) -> str:
    """계산 세대와 분리된 셀의 공간 동일성.

    같은 ``(q, r)``도 격자 수학이나 반지름이 다르면 다른 공간이다. 반대로 붓이나 sampling이
    달라져도 같은 격자 셀은 같은 공간이므로 ``paint_fp``는 넣지 않는다.
    """
    radius = json.dumps(float(radius_u), allow_nan=False, separators=(",", ":"))
    return f"{grid_version}:{radius}:{cell[0]}:{cell[1]}"


def _segment_key(segment: Segment) -> tuple:
    return (
        segment.a.at,
        segment.a.client_seq,
        segment.b.at,
        segment.b.client_seq,
    )


def _fix_identity(fix: WalkFix) -> tuple:
    return (fix.client_seq, fix.chain_index, fix.at, fix.lat, fix.lng)


def _chain_features(segments: list[Segment]) -> list[dict[str, object]]:
    grouped: dict[int, list[Segment]] = defaultdict(list)
    for segment in segments:
        if segment.chain_index < 0:
            raise ValueError("segment chain_index는 0 이상이어야 한다")
        grouped[segment.chain_index].append(segment)

    features: list[dict[str, object]] = []
    for chain_index in sorted(grouped):
        chain = sorted(grouped[chain_index], key=_segment_key)
        for previous, current in pairwise(chain):
            if _fix_identity(previous.b) != _fix_identity(current.a):
                raise ValueError(
                    f"chain {chain_index}의 segment가 이어지지 않는다: "
                    f"{previous.b.client_seq} -> {current.a.client_seq}"
                )

        coordinates = [[chain[0].a.lng, chain[0].a.lat]]
        coordinates.extend([segment.b.lng, segment.b.lat] for segment in chain)
        durations = []
        distances = []
        speeds = []
        moving = []
        for segment in chain:
            if not math.isfinite(segment.dt) or segment.dt <= 0:
                raise ValueError("accepted segment dt는 유한한 양수여야 한다")
            if not math.isfinite(segment.dist) or segment.dist < 0:
                raise ValueError("accepted segment dist는 유한한 0 이상이어야 한다")
            durations.append(segment.dt)
            distances.append(segment.dist)
            speeds.append(segment.dist / segment.dt)
            moving.append(segment.moving)
        features.append(
            {
                "type": "Feature",
                "id": f"chain:{chain_index}",
                "properties": {
                    "kind": "accepted_chain",
                    "chain_index": chain_index,
                    "segment_count": len(chain),
                    "source_segment_s": math.fsum(segment.dt for segment in chain),
                    # 네 배열의 index는 LineString의 좌표 edge index와 같다. speed는 기기가
                    # 직접 준 값이 아니라 canonical Segment의 dist / dt 파생값이다.
                    "segment_duration_s": durations,
                    "segment_distance_m": distances,
                    "segment_speed_mps": speeds,
                    "segment_moving": moving,
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": coordinates,
                },
            }
        )
    return features


def _cell_features(sheet: Cellophane) -> list[dict[str, object]]:
    occupancy_cells = set(sheet.occupancy)
    peak_cells = set(sheet.peak)
    if occupancy_cells != peak_cells:
        raise ValueError(
            "occupancy와 peak의 셀 집합이 다르다: "
            f"occupancy_only={sorted(occupancy_cells - peak_cells)}, "
            f"peak_only={sorted(peak_cells - occupancy_cells)}"
        )

    features: list[dict[str, object]] = []
    for q, r in sorted(occupancy_cells):
        occupancy_s = sheet.occupancy[(q, r)]
        peak = sheet.peak[(q, r)]
        if not math.isfinite(occupancy_s) or occupancy_s < 0:
            raise ValueError(f"cell {(q, r)}의 occupancy_s는 유한한 0 이상이어야 한다")
        if not math.isfinite(peak) or not 0 <= peak <= 1:
            raise ValueError(f"cell {(q, r)}의 peak는 유한한 0 이상 1 이하여야 한다")

        cell = (q, r)
        identifier = spatial_cell_id(sheet.grid_version, sheet.radius_u, cell)
        # cells.py 의 경계는 Android Canvas용 시계 방향이다. GeoJSON 외곽 링은
        # RFC 7946의 right-hand rule에 맞춰 반시계 방향으로 뒤집는다.
        boundary = reversed(hex_boundary_latlng(q, r, sheet.radius_u))
        ring = [[lng, lat] for lat, lng in boundary]
        ring.append(ring[0].copy())
        features.append(
            {
                "type": "Feature",
                "id": identifier,
                "properties": {
                    "kind": "cell",
                    "cell_id": identifier,
                    "q": q,
                    "r": r,
                    "occupancy_s": occupancy_s,
                    "peak": peak,
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [ring],
                },
            }
        )
    return features


def cellophane_feature_collection(
    sheet: Cellophane,
    segments: Iterable[Segment],
) -> dict[str, object]:
    """Cellophane + canonical Segment 열을 화면과 API가 공유할 GeoJSON으로 만든다.

    Feature 순서는 chain_index 오름차순의 LineString 뒤에 ``(q, r)`` 오름차순 Polygon이다.
    ``occupancy_mass_s``와 ``source_segment_s``는 반올림하지 않아 계산 오차를 숨기지 않는다.
    """
    if sheet.grid_version != GRID_VERSION:
        raise ValueError(
            f"지원하지 않는 grid_version: {sheet.grid_version!r} (지원: {GRID_VERSION!r})"
        )
    segment_list = list(segments)
    source_segment_s = math.fsum(segment.dt for segment in segment_list)
    occupancy_mass_s = math.fsum(sheet.occupancy.values())
    mass_error_s = occupancy_mass_s - source_segment_s
    chains = _chain_features(segment_list)
    cells = _cell_features(sheet)

    return {
        "type": "FeatureCollection",
        "meta": {
            "cellophane_geojson_version": CELLOPHANE_GEOJSON_VERSION,
            "session_id": sheet.walk_id,
            "paint_version": sheet.paint_version,
            "paint_fp": sheet.paint_fp,
            "grid_version": sheet.grid_version,
            "radius_u": sheet.radius_u,
            "profile_name": sheet.profile,
            "profile_fp": sheet.profile_fp,
            "sample_step_m": sheet.sample_step_m,
            "source_segment_s": source_segment_s,
            "occupancy_mass_s": occupancy_mass_s,
            "mass_error_s": mass_error_s,
            "mass_conserved": math.isclose(
                occupancy_mass_s,
                source_segment_s,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ),
            "segment_count": len(segment_list),
            "chain_count": len(chains),
            "cell_count": len(cells),
        },
        "features": [*chains, *cells],
    }


def dumps_cellophane_geojson(sheet: Cellophane, segments: Iterable[Segment]) -> str:
    """같은 입력은 byte-for-byte 같은 JSON을 만든다."""
    return json.dumps(
        cellophane_feature_collection(sheet, segments),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
