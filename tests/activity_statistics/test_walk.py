from dataclasses import replace

import pytest

from app.features.activity_statistics.common import ProjectionIdentity, StatisticsError
from app.features.activity_statistics.walk import (
    WalkMetrics,
    WalkSelection,
    project_walks,
    summarize_walks,
)
from tests.activity_statistics.fixtures import (
    CLIENT_W2,
    GENERATION,
    MINUTE,
    VERSIONS,
    selection,
    session,
    walk_source,
)


def project(*changes, versions=VERSIONS):
    return project_walks(changes, identity=GENERATION, expected_versions=versions)


def summary(projection, **kwargs):
    return summarize_walks(projection, owner_id="owner-1", from_ms=0, to_ms=20 * MINUTE, **kwargs)


def test_multi_pet_walk_is_one_owner_measurement_with_separate_participation():
    projection = project(selection(), selection())
    owner = summary(projection)
    assert (owner.recorded_walk_count, owner.observed_walk_count, owner.moving_distance_m) == (
        1,
        1,
        400,
    )
    assert summary(projection, pet_id="p1").moving_distance_m == 400
    assert summary(projection, pet_id="p2").moving_distance_m == 400
    assert summary(projection, pet_id="p3").recorded_walk_count == 0
    assert owner.sources[0].source.analysis_id == "analysis-1"
    assert owner.sources[0].source.receipt_id == "receipt-1"
    assert owner.avg_speed_mps == pytest.approx(400 / 480)


def test_no_pet_walk_is_retained_for_owner_without_inventing_participant():
    source = replace(walk_source(), session=session(pets=()))
    projection = project(selection(source))
    assert summary(projection).recorded_walk_count == 1
    assert summary(projection, pet_id="p1").recorded_walk_count == 0


def test_window_selects_entire_walk_by_end_with_half_open_boundaries():
    projection = project(selection())
    before = summarize_walks(projection, owner_id="owner-1", from_ms=0, to_ms=10 * MINUTE)
    after = summarize_walks(projection, owner_id="owner-1", from_ms=10 * MINUTE, to_ms=11 * MINUTE)
    assert before.recorded_walk_count == 0
    assert after.moving_distance_m == 400
    assert after.window_basis == "walk_end"
    assert (
        summarize_walks(projection, owner_id="owner-2", from_ms=0, to_ms=20 * MINUTE).sources == ()
    )


@pytest.mark.parametrize("origin", ["mock", "mixed", "unknown"])
def test_non_device_evidence_is_recorded_but_not_counted_as_observed(origin):
    result = summary(project(selection(replace(walk_source(), evidence_origin=origin))))
    assert result.recorded_walk_count == 1 and result.observed_walk_count == 0
    assert result.moving_distance_m is None
    assert result.exclusions == (("non_device_evidence", 1),)


def test_unavailable_is_not_zero_and_zero_observation_has_no_average_speed():
    unavailable = replace(walk_source(), metrics=None, observation_reason="no_observed_intervals")
    missing = summary(project(selection(unavailable)))
    assert missing.moving_s is None and missing.stop_count is None
    assert missing.exclusions == (("no_observed_intervals", 1),)
    stationary = replace(walk_source(), metrics=WalkMetrics(0, 0, 1, 600))
    zero = summary(project(selection(stationary)))
    assert zero.observed_walk_count == 1 and zero.moving_distance_m == 0
    assert zero.avg_speed_mps is None


def test_incompatible_versions_are_explicitly_excluded():
    future = replace(walk_source(), versions=replace(VERSIONS, calculation=5))
    result = summary(project(selection(future)))
    assert result.recorded_walk_count == 1 and result.observed_walk_count == 0
    assert result.exclusions == (("unsupported_analysis_versions", 1),)


def test_new_analysis_replaces_head_and_participant_correction_does_not_double_count():
    old = selection()
    new_source = replace(
        walk_source(), analysis_id="analysis-2", metrics=WalkMetrics(500, 480, 1, 120)
    )
    updated = selection(new_source, revision=2)
    corrected = selection(replace(new_source, session=session(pets=("p2",))), revision=3)
    projection = project(corrected, old, updated, old, corrected)
    assert summary(projection).moving_distance_m == 500
    assert summary(projection, pet_id="p1").recorded_walk_count == 0
    assert summary(projection, pet_id="p2").recorded_walk_count == 1
    assert projection.contributions[0].selection_revision == 3


def test_average_is_weighted_by_same_eligible_measurements():
    second = replace(
        walk_source(),
        session=session(server_id="walk-2", client=CLIENT_W2),
        analysis_id="analysis-2",
        metrics=WalkMetrics(100, 100, 0, 0),
    )
    result = summary(project(selection(), selection(second)))
    assert result.avg_speed_mps == pytest.approx(500 / 580)


def test_withdrawal_survives_replay_without_resurrection_and_new_generation_rebuilds():
    removed = WalkSelection("owner-1", "walk-1", 2, None)
    projection = project(selection(), removed, selection(), removed)
    assert summary(projection).recorded_walk_count == 0
    rebuilt = project_walks(
        projection.selections,
        identity=ProjectionIdentity("rebuild-2"),
        expected_versions=VERSIONS,
    )
    assert rebuilt.contributions == projection.contributions
    with pytest.raises(StatisticsError, match="walk_already_withdrawn"):
        project(selection(), removed, selection(revision=3))


@pytest.mark.parametrize(
    "changes,code",
    [
        ((selection(revision=2),), "selection_gap"),
        ((selection(), selection(revision=3)), "selection_gap"),
        (
            (selection(), selection(replace(walk_source(), metrics=WalkMetrics(1, 1, 0, 0)))),
            "selection_payload_conflict",
        ),
        (
            (
                selection(),
                selection(replace(walk_source(), metrics=WalkMetrics(1, 1, 0, 0)), revision=2),
            ),
            "analysis_payload_conflict",
        ),
    ],
)
def test_invalid_history_cannot_publish_partial_summary(changes, code):
    with pytest.raises(StatisticsError, match=code):
        project(*changes)


def test_client_identity_cannot_change_between_analysis_heads():
    changed = replace(walk_source(), analysis_id="analysis-2", session=session(client=CLIENT_W2))
    with pytest.raises(StatisticsError, match="walk_identity_conflict"):
        project(selection(), selection(changed, revision=2))


@pytest.mark.parametrize("metrics", [(-1, 0, 0, 0), (1, True, 0, 0), (1.5, 0, 0, 0)])
def test_measurement_contract_rejects_invalid_numbers(metrics):
    with pytest.raises(StatisticsError, match="invalid_nonnegative_integer"):
        WalkMetrics(*metrics)


def test_measurement_cannot_exceed_canonical_wall_time():
    with pytest.raises(StatisticsError, match="invalid_walk_duration"):
        replace(walk_source(), metrics=WalkMetrics(100, 601, 0, 0))


def test_same_client_cannot_be_counted_as_two_server_walks():
    second = replace(walk_source(), analysis_id="analysis-2", session=session(server_id="walk-2"))
    with pytest.raises(StatisticsError, match="client_walk_conflict"):
        project(selection(), selection(second))


def test_new_analysis_cannot_silently_change_session_timestamps():
    changed = replace(walk_source(), analysis_id="analysis-2", ended_ms=11 * MINUTE)
    with pytest.raises(StatisticsError, match="walk_identity_conflict"):
        project(selection(), selection(changed, revision=2))


def test_other_owner_withdrawal_cannot_reuse_server_walk_identity():
    with pytest.raises(StatisticsError, match="walk_identity_conflict"):
        project(selection(), WalkSelection("owner-2", "walk-1", 1, None))
