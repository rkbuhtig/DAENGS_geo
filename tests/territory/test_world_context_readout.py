"""world_context_readout 의 순수함수만. 네트워크·DB 는 스파이크 실행의 몫이다."""

from scripts.spikes.territory_paint.world_context_readout import (
    classify,
    in_ring,
    nearest_terrain,
    probes_from_latent,
    terrain_index,
)

# 대치동 근방 좌표 스케일의 작은 정사각형 링 (약 110m 변)
RING = [(37.4900, 127.0500), (37.4900, 127.0510),
        (37.4910, 127.0510), (37.4910, 127.0500), (37.4900, 127.0500)]


def test_in_ring_inside_and_outside():
    assert in_ring((37.4905, 127.0505), RING)
    assert not in_ring((37.4920, 127.0505), RING)
    # 경계 밖 — 같은 위도인데 경도가 링 서쪽
    assert not in_ring((37.4905, 127.0490), RING)


def test_classify_maps_fixed_kinds_only():
    assert classify({"type": "node", "tags": {"highway": "crossing"}}) == "crossing"
    assert classify({"type": "node", "tags": {"highway": "traffic_signals"}}) == "crossing"
    assert classify({"type": "node", "tags": {"natural": "tree"}}) == "tree"
    assert classify({"type": "way", "tags": {"leisure": "park"}}) == "park"
    assert classify({"type": "way", "tags": {"waterway": "stream"}}) == "water"
    # 등록 밖 부류는 안 받는다 — 결과를 보고 부류를 늘리면 사전 등록 위반이다
    assert classify({"type": "node", "tags": {"amenity": "cafe"}}) is None
    assert classify({"type": "way", "tags": {"building": "yes"}}) is None


def test_area_kind_inside_reads_zero_distance():
    ring_geom = [{"lat": lat, "lon": lng} for lat, lng in RING]
    index = terrain_index({"elements": [
        {"type": "way", "tags": {"leisure": "park", "name": "테스트공원"},
         "geometry": ring_geom},
    ]})
    inside = nearest_terrain((37.4905, 127.0505), index)
    assert inside["park"]["m"] == 0.0
    assert inside["park"]["name"] == "테스트공원"
    # 밖이면 꼭짓점 최근접 — 0 이 아니어야 한다
    outside = nearest_terrain((37.4930, 127.0505), index)
    assert outside["park"]["m"] > 0.0


def test_probes_use_actual_stop_centroid_not_latent():
    payload = {"personas": [{
        "id": "P", "kind": "planted",
        "truth_only": {
            "spots": [{"spot_id": "A0", "kind": "A", "at": [37.4900, 127.0500]}],
            "events": [
                {"walk_id": "P-000", "kind": "A", "spot_id": "A0",
                 "latent_at": [37.4900, 127.0500],
                 "actual_stop_at": [37.4902, 127.0500], "dwell_s": 40.0},
                {"walk_id": "P-001", "kind": "A", "spot_id": "A0",
                 "latent_at": [37.4900, 127.0500],
                 "actual_stop_at": [37.4904, 127.0500], "dwell_s": 50.0},
                {"walk_id": "P-002", "kind": "C", "spot_id": None,
                 "latent_at": None,
                 "actual_stop_at": [37.4910, 127.0510], "dwell_s": 12.0},
            ],
        },
    }]}
    probes = probes_from_latent(payload)
    a0 = next(p for p in probes if p["probe"] == "P:A0")
    # 실제 멈춤 둘의 중심 — 심은 좌표가 아니다
    assert abs(a0["at"][0] - 37.4903) < 1e-9
    assert a0["stops"] == 2
    c = [p for p in probes if p["kind"] == "C"]
    assert len(c) == 1 and c[0]["stops"] == 1


def test_probes_skip_spot_without_events_falls_back_to_latent():
    payload = {"personas": [{
        "id": "P", "kind": "planted",
        "truth_only": {
            "spots": [{"spot_id": "D0", "kind": "D", "at": [37.4901, 127.0501]}],
            "events": [],
        },
    }]}
    probes = probes_from_latent(payload)
    d0 = next(p for p in probes if p["probe"] == "P:D0")
    assert d0["at"] == [37.4901, 127.0501]
    assert d0["stops"] == 0
