"""Run with --with shapely --with pyproj; no live APIs or private SGIS files needed."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

pytest.importorskip("shapely")
pytest.importorskip("pyproj")

from pyproj import Transformer
from shapely.geometry import box, mapping

from scripts.spikes.storyboard_and_regions.build import build_story, context_at
from scripts.spikes.storyboard_and_regions.geometry import Regions

START = datetime(2026, 9, 4, tzinfo=UTC)
X, Y = Transformer.from_crs(4326, 5179, always_xy=True).transform(127.05, 37.487)


def regions():
    return Regions([
        {"id": "sgis:A", "name": "A동", "geometry": mapping(box(X-2000, Y-2000, X, Y+2000))},
        {"id": "sgis:B", "name": "B동", "geometry": mapping(box(X, Y-2000, X+2000, Y+2000))},
    ], {"source": "test-fixture"})


def segment(index, a_xy, b_xy, start=0, end=10, accuracy=0):
    reverse = Transformer.from_crs(5179, 4326, always_xy=True).transform

    def fix(xy, seconds):
        lng, lat = reverse(*xy)
        return SimpleNamespace(lng=lng, lat=lat, at=START+timedelta(seconds=seconds),
                               accuracy_m=accuracy)

    return SimpleNamespace(a=fix(a_xy, start), b=fix(b_xy, end), dt=end-start,
                           dist=abs(a_xy[0]-b_xy[0]), chain_index=index)


def test_crossing_splits_length_and_preserves_return():
    catalog = regions()
    runs = catalog.ordered_runs([
        segment(0, (X-100, Y), (X+100, Y)),
        segment(0, (X+100, Y), (X-100, Y), start=10, end=20),
    ], START)
    assert [r["regions"][0]["name"] for r in runs] == ["A동", "B동", "A동"]
    assert sum(r["distance_m"] for r in runs) == pytest.approx(400)
    assert runs[0]["end_s"] == pytest.approx(5)
    assert runs[-1]["end_s"] == 20


def test_gaps_and_explicit_chains_cannot_merge_same_region():
    catalog = regions()
    runs = catalog.ordered_runs([
        segment(0, (X-100, Y), (X-50, Y)),
        segment(0, (X-50, Y), (X-20, Y), start=100, end=110),
        segment(1, (X-20, Y), (X-10, Y), start=110, end=120),
    ], START)
    assert len(runs) == 3
    assert [(r["start_s"], r["end_s"]) for r in runs] == [(0, 10), (100, 110), (110, 120)]


def test_accuracy_band_is_not_a_confident_region():
    catalog = regions()
    lng, lat = catalog.reverse(X+1, Y)
    result = catalog.locate(lng, lat, accuracy_m=3)
    assert result["status"] == "boundary_uncertain"
    assert result["regions"][0]["name"] == "B동"


def test_overlapping_regions_do_not_choose_first():
    catalog = Regions([
        {"id": "A", "name": "A", "geometry": mapping(box(X-10, Y-10, X+10, Y+10))},
        {"id": "B", "name": "B", "geometry": mapping(box(X-10, Y-10, X+10, Y+10))},
    ], {})
    result = catalog.locate(*catalog.reverse(X, Y))
    assert result["status"] == "boundary_uncertain"
    assert len(result["regions"]) == 2


def context():
    return {"parks": [], "shops": [], "water": [], "river_names": set(),
            "snapshots": {"parks": {"status": "known"}, "rivers": {"status": "known"},
                          "commerce": {"status": "known", "query": {
                              "cx": 127.052, "cy": 37.487, "radius": 1200}}}}


def test_commerce_circle_must_be_fully_inside_collected_area():
    catalog = regions()
    ctx = context()
    cx, cy = catalog.forward(127.052, 37.487)
    assert context_at([127.052, 37.487], ctx, catalog)["commerce"]["complete"]
    edge = catalog.reverse(cx+1100, cy)
    assert not context_at(edge, ctx, catalog)["commerce"]["complete"]
    ctx["snapshots"]["commerce"]["status"] = "partial"
    assert not context_at([127.052, 37.487], ctx, catalog)["commerce"]["complete"]


def test_story_order_no_pin_and_no_invented_gap_path():
    catalog = regions()
    story = build_story(catalog, context(), with_gap=True, with_pin=False)
    scenes = story["scenes"]
    assert scenes[0]["kind"] == "start" and scenes[-1]["kind"] == "end"
    assert [s["at_s"] for s in scenes] == sorted(s["at_s"] for s in scenes)
    assert not any(s["kind"] == "pin" for s in scenes)
    assert sum(s["kind"] == "game" for s in scenes) == 1
    assert len(story["gaps"]) == 1
    gap = story["gaps"][0]
    gap_start, gap_end = gap["start_s"], gap["start_s"]+gap["duration_s"]
    assert not any(s["start_s"] < gap_end and s["end_s"] > gap_start
                   for s in story["segments"])
    assert not any(gap_start < s["at_s"] < gap_end for s in scenes)
    assert not any(r["start_s"] < gap_end and r["end_s"] > gap_start for r in story["runs"])
