"""실제 지도 위 Cellophane 통계 전환 화면의 얇은 프론트 계약."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "app" / "static" / "cellophane_distribution.html").read_text(encoding="utf-8")


def test_viewer_loads_the_app_naver_map_and_fixed_distribution_payload():
    assert "fetch('/map/client-config')" in HTML
    assert "https://oapi.map.naver.com/openapi/v3/maps.js" in HTML
    assert "new naver.maps.Map" in HTML
    assert "state.config.fallback !== 'osm'" in HTML
    assert "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" in HTML
    assert "© OpenStreetMap contributors" in HTML
    assert "DATA_URL = '/cellophane-distribution/data'" in HTML
    assert "state.payload.format_version !== 1" in HTML
    assert "state.authWatchTimer = setInterval" in HTML
    assert "void useOsmFallback(error)" in HTML
    assert "setTimeout(resolve,1500)" not in HTML


def test_viewer_switches_one_metric_at_a_time_without_recomputing_statistics():
    for metric in (
        "visit_rate",
        "total_time",
        "conditional_dwell",
        "time_utilization",
        "walk_utilization",
    ):
        assert metric in HTML
    assert "item.row.values[state.metric]" in HTML
    assert "item.row.numerators[state.metric]" in HTML
    assert "state.payload.metrics[state.metric]" in HTML
    assert "Math.sqrt(ratio)" in HTML


def test_viewer_draws_mass_regions_as_separate_boundaries_with_receipts():
    assert 'data-region="0.5"' in HTML
    assert 'data-region="0.8"' in HTML
    assert 'data-region="0.95"' in HTML
    assert "region.boundary_edges.forEach" in HTML
    assert "region.achieved_mass" in HTML
    assert "region.cell_count" in HTML
    assert "DISTRIBUTION_METRICS" in HTML


def test_viewer_exposes_value_denominator_generation_and_rendering_rule():
    assert 'id="r-denominator"' in HTML
    assert 'id="r-paint"' in HTML
    assert 'id="r-population"' in HTML
    assert 'id="d-receipt"' in HTML
    assert "formatReceiptPart" in HTML
    assert "값/최댓값 제곱근 · alpha 5–62%" in HTML
    assert "셀을 누르면 실제 값과 분자·분모" in HTML


def test_viewer_never_loads_or_names_latent_truth():
    for forbidden in (
        "east_loop",
        "south_outback",
        "north_park",
        "population_truth",
        "truth.json",
    ):
        assert forbidden not in HTML
