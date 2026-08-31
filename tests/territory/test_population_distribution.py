"""30회 통계 지도 payload는 latent truth 없이 계산 영수증과 공간 영역만 제공한다."""

import json

from scripts.spikes.territory_paint.population_distribution import (
    METRICS,
    build_distribution_payload,
    main,
    region_boundary_edges,
)


def test_distribution_payload_contains_five_metrics_and_nested_mass_regions():
    payload = build_distribution_payload()

    assert payload["format_version"] == 1
    assert payload["coordinate_order"] == "lat,lng"
    assert payload["sample_count"] == 30
    assert payload["cell_count"] == len(payload["cells"]) > 100
    assert tuple(payload["metrics"]) == METRICS
    assert payload["metrics"]["visit_rate"]["denominator"] == 30.0
    assert payload["metrics"]["conditional_dwell"]["denominator"] == "per_cell"

    for metric in ("time_utilization", "walk_utilization"):
        regions = payload["regions"][metric]
        assert [region["target_mass"] for region in regions] == [0.5, 0.8, 0.95]
        assert all(region["achieved_mass"] >= region["target_mass"] for region in regions)
        cell_sets = [set(region["cell_ids"]) for region in regions]
        assert cell_sets[0] <= cell_sets[1] <= cell_sets[2]
        assert all(region["boundary_edges"] for region in regions)


def test_distribution_payload_does_not_expose_generator_truth_labels():
    encoded = json.dumps(build_distribution_payload(), ensure_ascii=False, sort_keys=True)

    for forbidden in (
        "east_loop",
        "south_outback",
        "north_park",
        "exploration",
        '"branch"',
        '"holds"',
        '"seed"',
    ):
        assert forbidden not in encoded


def test_region_boundary_removes_the_shared_edge_between_adjacent_hexes():
    one = region_boundary_edges(frozenset({(0, 0)}), 8.0)
    adjacent = region_boundary_edges(frozenset({(0, 0), (1, 0)}), 8.0)

    assert len(one) == 6
    assert len(adjacent) == 10


def test_distribution_cli_writes_the_same_payload(tmp_path):
    output = tmp_path / "cellophane-distribution.json"
    assert main(["--out", str(output)]) == 0

    assert json.loads(output.read_text(encoding="utf-8")) == build_distribution_payload()
    assert output.read_bytes().endswith(b"\n")
