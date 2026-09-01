"""연속 원 × Hex 실제 지도 viewer payload 계약."""

import json

import pytest

from scripts.spikes.territory_paint import continuous_hex_visualization as visualization
from scripts.spikes.territory_paint.continuous_hex_comparison import METRICS


@pytest.fixture(scope="module")
def payload():
    return visualization.build_visualization_payload()


def test_visualization_payload_contains_common_raster_and_three_hex_resolutions(payload):
    assert payload["format_version"] == 2
    assert payload["coordinate_order"] == "lat,lng"
    assert payload["population"]["sample_count"] == 30
    assert len(payload["reference"]["pixels"]) > 1000
    assert [row["radius_u"] for row in payload["radii"]] == [4.0, 8.0, 12.0]

    bounds = payload["reference"]["bounds"]
    assert bounds["width"] == bounds["max_x"] - bounds["min_x"] + 1
    assert bounds["height"] == bounds["max_y"] - bounds["min_y"] + 1
    assert set(payload["reference"]["metrics"]) == set(METRICS)
    assert all(set(pixel["values"]) == set(METRICS) for pixel in payload["reference"]["pixels"])


def test_visualization_payload_freezes_one_metric_specific_exposure_for_all_layers(payload):
    exposure = payload["exposure"]

    assert exposure["curve"] == "one_minus_exp"
    assert exposure["max_alpha"] == pytest.approx(0.82)
    assert set(exposure["metrics"]) == set(METRICS)
    assert exposure["metrics"]["visit_rate"] == {
        "basis": "value",
        "scale": 0.5,
        "scale_unit": "ratio",
    }
    assert all(spec["scale"] > 0 for spec in exposure["metrics"].values())
    assert all(
        spec["basis"] == "area_density"
        for metric, spec in exposure["metrics"].items()
        if metric != "visit_rate"
    )


def test_hex_geometry_and_comparison_receipts_are_server_supplied(payload):
    for radius in payload["radii"]:
        assert radius["cells"]
        assert radius["cell_area_m2_at_origin"] > 0
        assert radius["comparison"]["mass"]["absolute_error_s"] < 1e-8
        assert 0 <= radius["comparison"]["support"]["sampled_area_iou"] <= 1
        assert set(radius["comparison"]["metrics"]) == set(METRICS)
        assert all(len(cell["boundary"]) == 6 for cell in radius["cells"])
        assert all(set(cell["values"]) == set(METRICS) for cell in radius["cells"])


def test_each_radius_contains_reconstructed_field_and_a_b_c_receipts(payload):
    for radius in payload["radii"]:
        reconstructed = radius["reconstructed"]
        comparison = radius["reconstruction_comparison"]

        assert reconstructed["pixel_m"] == payload["reference"]["pixel_m"]
        assert reconstructed["pixels"]
        assert all(set(pixel["values"]) == set(METRICS) for pixel in reconstructed["pixels"])
        assert comparison["mass"]["reconstructed_absolute_error_s"] < 1e-8
        assert comparison["support"]["leakage_pixels"] == 0
        assert comparison["support"]["missing_pixels"] == 0
        assert set(comparison["raw_piecewise"]["metrics"]) == set(METRICS)
        assert set(comparison["reconstructed"]["metrics"]) == set(METRICS)


def test_both_projections_expose_50_80_95_percent_region_boundaries(payload):
    for metric in ("time_utilization", "walk_utilization"):
        reference_regions = payload["reference"]["regions"][metric]
        assert [region["target_mass"] for region in reference_regions] == [0.5, 0.8, 0.95]
        assert all(region["boundary_edges"] for region in reference_regions)
        for radius in payload["radii"]:
            regions = radius["regions"][metric]
            assert [region["target_mass"] for region in regions] == [0.5, 0.8, 0.95]
            assert all(region["boundary_edges"] for region in regions)
            reconstructed_regions = radius["reconstructed"]["regions"][metric]
            assert [region["target_mass"] for region in reconstructed_regions] == [0.5, 0.8, 0.95]
            assert all(region["boundary_edges"] for region in reconstructed_regions)


def test_visualization_payload_does_not_expose_latent_generator_labels(payload):
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "east_loop",
        "south_outback",
        "north_park",
        "exploration",
        '"branch"',
        '"hold"',
        '"seed"',
    ):
        assert forbidden not in encoded
    assert payload["roles"]["reconstructed"] == "ephemeral_display_only_not_statistics_source"


def test_pixel_region_boundary_removes_an_internal_shared_edge():
    raster = visualization.RasterSpec(pixel_m=4.0)
    one = visualization.pixel_region_boundary_edges(frozenset({(0, 0)}), raster)
    adjacent = visualization.pixel_region_boundary_edges(frozenset({(0, 0), (1, 0)}), raster)

    assert len(one) == 4
    assert len(adjacent) == 6


def test_visualization_cli_writes_json_without_requiring_the_expensive_fixture_twice(
    tmp_path, monkeypatch
):
    expected = {"format_version": 2, "population": {"sample_count": 0}, "reference": {"pixels": []}, "radii": []}
    monkeypatch.setattr(visualization, "build_visualization_payload", lambda **_kwargs: expected)
    output = tmp_path / "visualization.json"

    assert visualization.main(["--out", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == expected
    assert output.read_bytes().endswith(b"\n")
