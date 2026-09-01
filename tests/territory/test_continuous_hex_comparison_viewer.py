"""연속 원 × Hex 실제 지도 비교 화면의 얇은 프론트 계약."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "app" / "static" / "continuous_hex_comparison.html").read_text(encoding="utf-8")


def test_viewer_uses_real_map_with_naver_and_osm_fallback():
    assert "fetch('/map/client-config')" in HTML
    assert "https://oapi.map.naver.com/openapi/v3/maps.js" in HTML
    assert "new naver.maps.Map" in HTML
    assert "new naver.maps.GroundOverlay" in HTML
    assert "L.imageOverlay" in HTML
    assert "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" in HTML
    assert "© OpenStreetMap contributors" in HTML
    assert "DATA_URL = '/continuous-hex-comparison/data'" in HTML
    assert "면적 단위가 없는 비교 payload입니다" in HTML


def test_viewer_switches_projection_metric_and_hex_resolution_without_recomputing_stats():
    for mode in ("reference", "hex", "reconstructed", "overlay"):
        assert f'data-mode="{mode}"' in HTML
    for metric in (
        "visit_rate",
        "total_time",
        "conditional_dwell",
        "time_utilization",
        "walk_utilization",
    ):
        assert metric in HTML
    assert "state.payload.radii.forEach" in HTML
    assert "cell.values[state.metric]" in HTML
    assert "pixel.values[metric]" in HTML
    assert "currentRadius().reconstructed" in HTML


def test_continuous_layer_is_a_smoothed_measurement_raster_not_a_second_heat_kernel():
    assert "buildRasterImage" in HTML
    assert "createImageData" in HTML
    assert "imageSmoothingEnabled = true" in HTML
    assert "imageSmoothingQuality = 'high'" in HTML
    assert "HeatMap" not in HTML
    assert "WeightedLocation" not in HTML


def test_all_three_layers_share_a_fixed_exponential_exposure_in_area_units():
    assert "state.payload.exposure.metrics[metric]" in HTML
    assert "exposure.basis === 'area_density' ? value / areaM2 : value" in HTML
    assert "1 - Math.exp(-exposed / scale)" in HTML
    assert "viewer-v2-2026-09-01-fixed-p85" not in HTML
    assert "/ maximum" not in HTML
    assert "Math.sqrt(ratio)" not in HTML
    assert 'id="r-exposure"' in HTML
    assert 'id="legend-scale"' in HTML


def test_hex_is_boundary_free_by_default_but_can_be_exposed_for_debugging():
    assert 'id="hex-debug" aria-pressed="false"' in HTML
    assert "strokeOpacity:state.hexDebug ? .5 : 0" in HTML
    assert "strokeWeight:state.hexDebug ? 1 : 0" in HTML
    assert "cell.boundary" in HTML


def test_viewer_exposes_mass_support_metric_and_region_comparison_receipts():
    for identifier in ("r-mass", "r-support", "r-distance", "region-summary"):
        assert f'id="{identifier}"' in HTML
    assert "reconstruction_comparison" in HTML
    assert "leakage_pixels" in HTML
    assert "normalized_l1" in HTML
    assert "mean_absolute_error" in HTML
    assert "comparison.raw_piecewise.mass_regions" in HTML
    assert "comparison.reconstructed.mass_regions" in HTML


def test_click_readout_compares_values_in_their_area_units():
    assert "referencePixelAt" in HTML
    assert "hexAt" in HTML
    assert "cell_area_m2_at_origin" in HTML
    assert "reference.pixel_m ** 2" in HTML
    assert "reconstructedPixelAt" in HTML
    assert 'id="d-reference"' in HTML
    assert 'id="d-hex"' in HTML
    assert 'id="d-reconstructed"' in HTML
    assert 'id="d-raw-difference"' in HTML
    assert 'id="d-reconstructed-difference"' in HTML
