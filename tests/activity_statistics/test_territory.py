from dataclasses import replace

import pytest

from app.features.activity_statistics.common import ProjectionIdentity, StatisticsError
from app.features.activity_statistics.territory import (
    ConfirmedCut,
    InitialOwner,
    TerritoryStatEvent,
    holding_time,
    project_territory,
    summarize_territory,
)
from tests.activity_statistics.fixtures import (
    COVERAGE,
    CUT,
    GENERATION,
    MINUTE,
    ownership_event,
    territory_events,
)


def project(events=None, *, coverage=COVERAGE, cut=CUT):
    return project_territory(
        territory_events() if events is None else events,
        identity=GENERATION,
        coverage=coverage,
        cut=cut,
    )


def test_certification_takeover_and_walk_independent_holding_match_hand_calculation():
    projection = project()
    p1 = summarize_territory(projection, pet_id="p1")
    p2 = summarize_territory(projection, pet_id="p2")
    assert (p1.acquisition_count, p1.takeover_count, p1.owned_site_count) == (1, 0, 0)
    assert (p1.held_site_ms, p1.verified_held_site_ms) == (10 * MINUTE, 8 * MINUTE)
    assert (p2.acquisition_count, p2.takeover_count, p2.owned_site_count) == (1, 1, 1)
    assert (p2.held_site_ms, p2.verified_held_site_ms) == (8 * MINUTE, 8 * MINUTE)
    assert p1.peak_owned_site_count == p2.peak_owned_site_count == 1
    assert p1.periods[0].period_id == ("season-1", "event-2", "A")
    assert p1.periods[0].end_event_id == "event-4"
    assert p1.periods[0].claim_id == "claim-2"
    assert p2.confirmed_through_ms == 20 * MINUTE


def test_duplicate_out_of_order_delivery_and_generation_replay_are_deterministic():
    events = territory_events()
    projection = project((*reversed(events), *events, *events))
    assert projection == project(events)
    rebuilt = project_territory(
        projection.events,
        identity=ProjectionIdentity("rebuild-2"),
        coverage=COVERAGE,
        cut=CUT,
    )
    assert rebuilt.periods == projection.periods and rebuilt.peaks == projection.peaks


def test_unchanged_does_not_open_period_or_increase_counts():
    unchanged = ownership_event(5, 18, pet="p2", previous="p2", verified=True, kind="UNCHANGED")
    result = summarize_territory(
        project((*territory_events(), unchanged), cut=replace(CUT, revision=5)),
        pet_id="p2",
    )
    assert result.acquisition_count == 1 and len(result.periods) == 1
    assert result.held_site_ms == 8 * MINUTE


def test_lagged_read_stops_at_confirmed_cut_and_missing_takeover_cannot_advance_it():
    partial = territory_events()[:3]
    before = project(partial, cut=ConfirmedCut("season-1", 3, 10 * MINUTE))
    assert summarize_territory(before, pet_id="p1").held_site_ms == 8 * MINUTE
    with pytest.raises(StatisticsError, match="event_gap"):
        project(partial)  # authoritative cut says revision 4 exists, but it is missing


def test_baseline_has_coverage_not_invented_acquisitions_and_closes_at_season_end():
    coverage = replace(COVERAGE, coverage_start_ms=5 * MINUTE, base_revision=10)
    init = TerritoryStatEvent(
        "season-1",
        "import",
        11,
        5 * MINUTE,
        "INITIALIZED",
        initial_owners=(InitialOwner("A", "p1", True), InitialOwner("B", "p1")),
    )
    close = TerritoryStatEvent("season-1", "close", 12, 30 * MINUTE, "SEASON_CLOSED")
    projection = project(
        [init, close], coverage=coverage, cut=ConfirmedCut("season-1", 12, 40 * MINUTE)
    )
    p1 = summarize_territory(projection, pet_id="p1")
    assert (p1.acquisition_count, p1.takeover_count, p1.owned_site_count) == (0, 0, 0)
    assert p1.peak_owned_site_count == 2
    assert p1.held_site_ms == 50 * MINUTE and p1.verified_held_site_ms == 25 * MINUTE
    assert p1.coverage_start_ms == 5 * MINUTE
    assert all(p.origin == "IMPORTED" and p.end_event_id == "close" for p in p1.periods)


def test_same_timestamp_uses_source_revision_for_peak_and_zero_length_periods():
    init = territory_events()[0]
    events = [
        init,
        ownership_event(2, 2),
        ownership_event(3, 2, site="B"),
        ownership_event(4, 2, pet="p2", previous="p1"),
    ]
    p1 = summarize_territory(project(events), pet_id="p1")
    assert p1.peak_owned_site_count == 2 and p1.owned_site_count == 1
    assert p1.held_site_ms == 18 * MINUTE
    assert p1.periods[0].ended_ms == p1.periods[0].started_ms


@pytest.mark.parametrize(
    "start,end,expected",
    [
        (0, 2, (0, 0)),
        (2, 4, (2, 0)),
        (4, 12, (8, 8)),
        (12, 20, (0, 0)),
        (3, 5, (2, 1)),
        (0, 20, (10, 8)),
    ],
)
def test_holding_overlap_is_half_open_and_certification_is_not_retroactive(start, end, expected):
    period = project().periods[0]
    assert holding_time(period, from_ms=start * MINUTE, to_ms=end * MINUTE) == tuple(
        value * MINUTE for value in expected
    )


@pytest.mark.parametrize(
    "events,cut,code",
    [
        (territory_events()[1:], CUT, "event_gap"),
        (territory_events()[:2] + territory_events()[3:], CUT, "event_gap"),
        (
            (*territory_events(), replace(territory_events()[1], pet_id="p3")),
            CUT,
            "event_revision_conflict",
        ),
        (
            (*territory_events(), replace(territory_events()[1], revision=5)),
            replace(CUT, revision=5),
            "event_identity_conflict",
        ),
        (
            territory_events(),
            replace(CUT, through_ms=11 * MINUTE),
            "event_time_reversed_or_unconfirmed",
        ),
        (territory_events(), replace(CUT, through_ms=30 * MINUTE), "season_close_required"),
    ],
)
def test_incomplete_or_conflicting_stream_is_rejected(events, cut, code):
    with pytest.raises(StatisticsError, match=code):
        project(events, cut=cut)


@pytest.mark.parametrize(
    "change,code",
    [
        ({"previous_pet_id": "p3"}, "previous_owner_mismatch"),
        ({"pet_id": "p1"}, "ownership_did_not_change"),
        ({"at_ms": 3 * MINUTE}, "event_time_reversed_or_unconfirmed"),
        ({"season_id": "other"}, "event_season_mismatch"),
    ],
)
def test_impossible_transition_cannot_be_counted(change, code):
    events = (*territory_events()[:3], replace(territory_events()[3], **change))
    with pytest.raises(StatisticsError, match=code):
        project(events)


def test_second_certification_requires_unchanged_source_event():
    event = ownership_event(4, 5, previous="p1", verified=True, kind="CERTIFIED")
    with pytest.raises(StatisticsError, match="invalid_certification"):
        project((*territory_events()[:3], event))


def test_no_event_can_follow_finalization_and_new_season_is_separate():
    close = TerritoryStatEvent("season-1", "close", 5, 30 * MINUTE, "SEASON_CLOSED")
    later = ownership_event(6, 30, pet="p3", site="B")
    with pytest.raises(StatisticsError, match="event_after_season_closed"):
        project((*territory_events(), close, later), cut=ConfirmedCut("season-1", 6, 31 * MINUTE))
    p1 = summarize_territory(project(), pet_id="never-participated")
    assert p1.acquisition_count == p1.held_site_ms == p1.peak_owned_site_count == 0


def test_baseline_cannot_count_same_site_twice():
    with pytest.raises(StatisticsError, match="duplicate_baseline_site"):
        replace(
            territory_events()[0], initial_owners=(InitialOwner("A", "p1"), InitialOwner("A", "p2"))
        )
