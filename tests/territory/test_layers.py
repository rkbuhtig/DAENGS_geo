"""셀로판 질의층 계약. `app/features/territory/layers.py`.

지키는 것 셋:

1. **태그는 관측된 시각에서 파생된다** — 원천에 박혀 있지 않다
2. **결과는 spec 과 분모를 달고 나온다** — 같은 spec 은 같은 지문, 같은 canvas
3. **값 연산과 존재 연산은 다른 답을 준다** — 이걸 섞으면 편향이 안 보인다
"""

import math
from datetime import UTC, date, datetime, timedelta

import pytest

from app.features.territory.layers import (
    Aggregation,
    LayerSpec,
    Projection,
    Selector,
    derive_tags,
    normalized_distance,
    rate_diff,
    rate_field,
    render,
    select,
)
from app.features.territory.paint import NARROW_STEP, BrushProfile, paint_sheet, paint_spec
from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkFix
from app.geo.cells import hex_cell, hex_center_latlng

EARTH_R = 6_371_000.0
RADIUS_U = 8.0
LAT, LNG = 37.4979, 127.0276
BRUSH = NARROW_STEP.name
BRUSH_FP = NARROW_STEP.fingerprint
PAINT_SPEC = paint_spec(RADIUS_U, NARROW_STEP)


def _sheet(walk_id: str, at: datetime, offset_m: float):
    """`offset_m` 만큼 남/북으로 떨어진 동서 직선 60m 를 걸은 장."""
    target = hex_cell(LAT, LNG, RADIUS_U)
    lat0, lng0 = hex_center_latlng(*target, RADIUS_U)
    lat = lat0 + math.degrees(offset_m / EARTH_R)
    fixes = [
        WalkFix(client_seq=i, chain_index=0, at=at + timedelta(seconds=i), lat=lat,
                lng=lng0 + math.degrees((i - 30) / (EARTH_R * math.cos(math.radians(lat0)))),
                accuracy_m=3.0, is_mock=False)
        for i in range(61)
    ]
    segs = compute_facts("w", "d", fixes[0].at, fixes[-1].at + timedelta(seconds=1),
                         fixes).trail.segments
    return paint_sheet(walk_id, at, segs, RADIUS_U, NARROW_STEP)


def _spec(metric: str = "walks", **tags) -> LayerSpec:
    return LayerSpec(
        selector=Selector.of(**tags),
        aggregation=Aggregation(metric=metric),
        projection=Projection.from_paint_spec(PAINT_SPEC),
    )


# ---- 태그 파생 ------------------------------------------------------------------------


def test_tags_come_from_the_observed_timestamp():
    tags = derive_tags(datetime(2026, 7, 15, 22, 30, tzinfo=UTC))
    assert tags["season"] == "summer"
    assert tags["time_band"] == "night"
    assert tags["quarter"] == "Q3"
    assert tags["day_type"] == "weekday"          # 2026-07-15 는 수요일


def test_december_is_winter_and_dawn_is_not_night():
    assert derive_tags(datetime(2026, 12, 3, 8, tzinfo=UTC))["season"] == "winter"
    assert derive_tags(datetime(2026, 12, 3, 2, tzinfo=UTC))["time_band"] == "dawn"
    assert derive_tags(datetime(2026, 12, 3, 22, tzinfo=UTC))["time_band"] == "night"


def test_weekend_is_derived_not_declared():
    assert derive_tags(datetime(2026, 7, 18, 9, tzinfo=UTC))["day_type"] == "weekend"


# ---- 선택 ----------------------------------------------------------------------------


def test_selector_ands_its_tags():
    sheets = [
        _sheet("summer-night", datetime(2026, 7, 1, 22, tzinfo=UTC), 0.0),
        _sheet("summer-day", datetime(2026, 7, 2, 13, tzinfo=UTC), 0.0),
        _sheet("winter-night", datetime(2026, 1, 3, 22, tzinfo=UTC), 0.0),
    ]
    assert len(select(sheets, _spec(season="summer"))) == 2
    assert len(select(sheets, _spec(time_band="night"))) == 2
    assert len(select(sheets, _spec(season="summer", time_band="night"))) == 1


def test_period_narrows_independently_of_tags():
    sheets = [_sheet(f"w{m}", datetime(2026, m, 5, 9, tzinfo=UTC), 0.0) for m in (3, 4, 5)]
    spec = LayerSpec(
        selector=Selector.of(since=date(2026, 4, 1), until=date(2026, 4, 30), season="spring"),
        aggregation=Aggregation(),
        projection=Projection.from_paint_spec(PAINT_SPEC),
    )
    assert len(select(sheets, spec)) == 1


def test_spec_picks_the_brush_generation_by_fingerprint():
    """같은 이름의 두 세대가 섞여 있으면 spec 이 명시한 지문의 장만 고른다."""
    old = _sheet("old", datetime(2026, 7, 1, 9, tzinfo=UTC), 0.0)
    other_profile = BrushProfile(BRUSH, (3.0, 8.0, 20.0), (1.0, 0.5, 0.1))
    target = hex_cell(LAT, LNG, RADIUS_U)
    lat0, lng0 = hex_center_latlng(*target, RADIUS_U)
    other_curve = paint_sheet(
        "other",
        old.at,
        compute_facts(
            "w",
            "d",
            old.at,
            old.at + timedelta(seconds=2),
            [
                WalkFix(client_seq=0, chain_index=0, at=old.at, lat=lat0, lng=lng0,
                        accuracy_m=3.0, is_mock=False),
                WalkFix(client_seq=1, chain_index=0, at=old.at + timedelta(seconds=1),
                        lat=lat0, lng=lng0, accuracy_m=3.0, is_mock=False),
            ],
        ).trail.segments,
        RADIUS_U,
        other_profile,
    )
    assert select([old, other_curve], _spec()) == [old]


def test_missing_generation_is_an_error_not_an_empty_map():
    """이름은 맞는데 그 세대가 하나도 없으면 **조용히 빈 지도를 주지 않는다.**

    데이터가 다른 세대뿐이라는 사실을 호출자가 알아야 한다 — 빈 canvas 를 주면 "안 갔다"
    로 읽힌다.
    """
    import pytest

    other_profile = BrushProfile(BRUSH, (3.0, 8.0, 20.0), (1.0, 0.5, 0.1))
    at = datetime(2026, 7, 1, 9, tzinfo=UTC)
    target = hex_cell(LAT, LNG, RADIUS_U)
    lat0, lng0 = hex_center_latlng(*target, RADIUS_U)
    fixes = [
        WalkFix(client_seq=0, chain_index=0, at=at, lat=lat0, lng=lng0,
                accuracy_m=3.0, is_mock=False),
        WalkFix(client_seq=1, chain_index=0, at=at + timedelta(seconds=1),
                lat=lat0, lng=lng0, accuracy_m=3.0, is_mock=False),
    ]
    only_other = paint_sheet(
        "other",
        at,
        compute_facts("w", "d", at, at + timedelta(seconds=2), fixes).trail.segments,
        RADIUS_U,
        other_profile,
    )
    with pytest.raises(ValueError, match="페인트 세대"):
        select([only_other], _spec())


def test_grid_version_gates_mixing():
    """radius 와 붓 이름이 같아도 격자 수학이 바뀌었으면 (q, r) 이 다른 자리다."""
    good = _sheet("v1", datetime(2026, 7, 1, 9, tzinfo=UTC), 0.0)
    future_spec = paint_spec(RADIUS_U, NARROW_STEP)
    future = type(good)(
        walk_id="v2",
        at=good.at,
        radius_u=good.radius_u,
        profile=good.profile,
        occupancy=good.occupancy,
        peak=good.peak,
        paint_version=good.paint_version,
        grid_version="hex-v2",
        profile_fp=good.profile_fp,
        sample_step_m=good.sample_step_m,
        paint_fp=type(future_spec)(
            paint_version=future_spec.paint_version,
            grid_version="hex-v2",
            radius_u=future_spec.radius_u,
            profile_name=future_spec.profile_name,
            profile_fp=future_spec.profile_fp,
            sample_step_m=future_spec.sample_step_m,
        ).fingerprint,
    )
    assert select([good, future], _spec()) == [good]


def test_brush_fingerprint_tracks_the_curve_not_the_name():
    a = BrushProfile("같은이름", (3.0, 8.0, 20.0), (1.0, 0.45, 0.15))
    b = BrushProfile("같은이름", (3.0, 8.0, 20.0), (1.0, 0.5, 0.1))
    c = BrushProfile("다른이름", (3.0, 8.0, 20.0), (1.0, 0.45, 0.15))
    assert a.fingerprint != b.fingerprint          # 곡선이 다르면 지문이 다르다
    assert a.fingerprint == c.fingerprint          # 이름은 지문에 안 들어간다


def test_profile_display_name_change_does_not_hide_the_same_generation():
    old = _sheet("old-name", datetime(2026, 7, 1, 9, tzinfo=UTC), 0.0)
    renamed_profile = BrushProfile(
        "새 표시 이름", NARROW_STEP.bands, NARROW_STEP.weights, NARROW_STEP.smooth
    )
    renamed_spec = LayerSpec(
        selector=Selector.of(),
        aggregation=Aggregation(),
        projection=Projection.from_paint_spec(paint_spec(RADIUS_U, renamed_profile)),
    )
    assert old.profile != renamed_spec.projection.brush
    assert old.paint_fp == renamed_spec.projection.paint_fp
    assert select([old], renamed_spec) == [old]


def test_sheets_from_another_grid_are_never_mixed_in():
    """격자가 다른 장은 셀 id 가 같은 자리를 뜻하지 않는다 — 조용히 겹치면 안 된다."""
    at = datetime(2026, 7, 1, 9, tzinfo=UTC)
    good = _sheet("same-grid", at, 0.0)
    target = hex_cell(LAT, LNG, 15.0)
    lat0, lng0 = hex_center_latlng(*target, 15.0)
    fixes = [
        WalkFix(client_seq=i, chain_index=0, at=at + timedelta(seconds=i),
                lat=lat0, lng=lng0 + math.degrees(i / (EARTH_R * math.cos(math.radians(lat0)))),
                accuracy_m=3.0, is_mock=False)
        for i in range(61)
    ]
    segs = compute_facts("w", "d", fixes[0].at, fixes[-1].at + timedelta(seconds=1),
                         fixes).trail.segments
    other = paint_sheet("other-grid", at, segs, 15.0, NARROW_STEP)
    assert select([good, other], _spec()) == [good]


# ---- 결과는 spec 과 분모를 단다 --------------------------------------------------------


def test_layer_carries_spec_and_denominator():
    sheets = [_sheet(f"w{i}", datetime(2026, 7, i + 1, 22, tzinfo=UTC), 0.0) for i in range(5)]
    sheets.append(_sheet("winter", datetime(2026, 1, 9, 22, tzinfo=UTC), 0.0))
    layer = render(sheets, _spec(season="summer"))
    assert layer.selected == 5 and layer.total == 6
    assert layer.spec.selector.label.startswith("season=summer")


def test_canvas_renderer_rejects_a_spatial_statistics_metric_early():
    with pytest.raises(ValueError, match="canvas metric"):
        render([], _spec(metric="visit_rate"))


def test_same_spec_same_fingerprint_and_canvas():
    """재현성 — spec 이 같으면 지문도 canvas 도 같다."""
    sheets = [_sheet(f"w{i}", datetime(2026, 7, i + 1, 22, tzinfo=UTC), 0.0) for i in range(4)]
    one, two = render(sheets, _spec(season="summer")), render(sheets, _spec(season="summer"))
    assert one.spec.fingerprint() == two.spec.fingerprint()
    assert one.canvas.keys() == two.canvas.keys()
    assert all(one.canvas[c].walks == two.canvas[c].walks for c in one.canvas)


def test_changing_any_compartment_changes_the_fingerprint():
    """selector·aggregation·projection 중 무엇이 바뀌어도 다른 지도다."""
    base = _spec(season="summer").fingerprint()
    assert _spec(season="winter").fingerprint() != base
    assert _spec(metric="occupancy", season="summer").fingerprint() != base
    other = LayerSpec(selector=Selector.of(season="summer"), aggregation=Aggregation(),
                      projection=Projection.from_paint_spec(paint_spec(15.0, NARROW_STEP)))
    assert other.fingerprint() != base


def test_spec_fingerprint_catches_a_curve_change_under_the_same_name():
    """**이름을 안 바꾸고 감쇠만 바꾸면** spec 지문이 달라져야 한다.

    화면에 띄우는 provenance 가 spec 지문 하나뿐이라, 여기서 안 갈리면 6 개월 뒤 "그 그림이
    어느 붓이었나" 를 따라갈 수 없다.
    """
    changed_profile = BrushProfile(BRUSH, (3.0, 8.0, 20.0), (1.0, 0.5, 0.1))
    changed = LayerSpec(
        selector=Selector.of(season="summer"), aggregation=Aggregation(),
        projection=Projection.from_paint_spec(paint_spec(RADIUS_U, changed_profile)))
    assert changed.fingerprint() != _spec(season="summer").fingerprint()


def test_projection_rejects_an_identity_that_disagrees_with_its_fields():
    import dataclasses

    import pytest

    projection = Projection.from_paint_spec(PAINT_SPEC)
    with pytest.raises(ValueError, match="projection paint_fp"):
        dataclasses.replace(projection, sample_step_m=projection.sample_step_m + 0.5)


# ---- 값 연산 vs 존재 연산 --------------------------------------------------------------


def test_rate_is_normalised_by_the_chosen_count():
    """여름 4회와 겨울 1회를 견줄 수 있어야 한다 — 횟수가 아니라 비율이라서."""
    summer = [_sheet(f"s{i}", datetime(2026, 7, i + 1, 22, tzinfo=UTC), 0.0) for i in range(4)]
    winter = [_sheet("w0", datetime(2026, 1, 9, 22, tzinfo=UTC), 0.0)]
    a = render(summer + winter, _spec(season="summer"))
    b = render(summer + winter, _spec(season="winter"))
    cell = hex_cell(LAT, LNG, RADIUS_U)
    assert math.isclose(rate_field(a)[cell], 1.0)
    assert math.isclose(rate_field(b)[cell], 1.0)      # 분모가 달라도 같은 비율


def test_support_difference_hides_a_bias_that_value_difference_shows():
    """**이 파일의 핵심.** 여름에 자주·겨울에 가끔 가는 칸.

    존재 연산으로는 양쪽 support 에 다 있어 `A − B` 에서 사라진다. 비율 차이는 남는다.
    """
    # 붓 도달(20m) **밖**이어야 그 산책이 이 칸을 안 칠한다. 12m 로 두면 양쪽 다 100% 가
    # 되어 편향이 만들어지지도 않는다 — 첫 판이 그렇게 틀렸다.
    far = 40.0
    summer = [_sheet(f"s{i}", datetime(2026, 7, (i % 28) + 1, 22, tzinfo=UTC),
                     0.0 if i < 9 else far) for i in range(10)]
    winter = [_sheet(f"w{i}", datetime(2026, 1, (i % 28) + 1, 22, tzinfo=UTC),
                     0.0 if i < 1 else far) for i in range(10)]
    a = render(summer + winter, _spec(season="summer"))
    b = render(summer + winter, _spec(season="winter"))
    cell = hex_cell(LAT, LNG, RADIUS_U)

    assert cell in a.support and cell in b.support     # 존재로는 양쪽에 다 있고
    assert cell not in (a.support - b.support)         # 차집합에서 사라진다
    assert rate_diff(a, b)[cell] > 0.5                      # 값으로는 크게 남는다


def test_identical_selections_have_zero_distance():
    sheets = [_sheet(f"w{i}", datetime(2026, 7, i + 1, 22, tzinfo=UTC), 0.0) for i in range(4)]
    layer = render(sheets, _spec(season="summer"))
    assert normalized_distance(layer, layer) == 0.0


def test_distance_grows_when_the_walked_line_moves():
    near = [_sheet(f"n{i}", datetime(2026, 7, i + 1, 22, tzinfo=UTC), 0.0) for i in range(3)]
    far = [_sheet(f"f{i}", datetime(2026, 1, i + 1, 22, tzinfo=UTC), 40.0) for i in range(3)]
    a = render(near + far, _spec(season="summer"))
    b = render(near + far, _spec(season="winter"))
    assert normalized_distance(a, b) > normalized_distance(a, a)
