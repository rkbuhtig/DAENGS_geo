from datetime import UTC, datetime

from scripts.spikes.walk_record_lab.core import Experiment, prepare, summarize
from scripts.spikes.walk_record_lab.selection import ReferenceWalk, select


def experiment(length=1000, taps=(), holds=(), **kwargs):
    return Experiment(scenario={
        "started_at": "2026-09-05T00:00:00Z", "session_id": "current", "dog_id": "dog",
        "origin": {"lat": 37.48928, "lng": 127.0545},
        "route": {"name": "line", "points_xy": [[0, 0], [length, 0]]},
        "motion": {"name": "steady", "base_speed_mps": 1, "holds": list(holds)},
        "sensor": {"kind": "perfect", "sample_interval_s": 5, "accuracy_m": 3}},
        taps=list(taps), **kwargs)


def selection(exp):
    artifacts, entries = prepare(exp)
    return select(artifacts, entries, exp.selection, exp.reference_walks)


def tap(at, id="a"):
    return {"id": id, "code": "sniffing", "at_s": at}


def test_clustered_actions_fill_largest_rear_then_front_gap():
    result = selection(experiment(taps=[tap(450), tap(470, "b")]))
    assert result["anchors"][0]["entry_ids"] == ["a", "b"]
    assert [s["reason"] for s in result["steps"][:3]] == [
        "action", "distance_fill", "distance_fill"]
    assert abs(result["steps"][1]["route_m"]-750) < 10
    assert abs(result["steps"][2]["route_m"]-200) < 10
    assert result["minimum_met"]


def test_pinless_walk_gets_environment_without_creating_behavior_evidence():
    exp = experiment()
    artifacts, entries = prepare(exp)
    chosen = select(artifacts, entries, exp.selection, [])
    result = summarize(exp, artifacts, entries, {}, chosen)
    assert len(chosen["anchors"]) >= 4
    assert len(result["environment_rows"]) >= 4
    assert len(result["scenes"]) > 2
    assert result["profile"]["evidence_ids"] == []


def test_short_walk_reports_shortfall_without_duplicate_queries():
    result = selection(experiment(40))
    assert len(result["anchors"]) == 1
    assert not result["minimum_met"]
    assert result["shortfall_reason"] == "insufficient_distinct_valid_route"


def test_action_minimum_does_not_leave_long_tail_unread():
    result = selection(experiment(1800, taps=[tap(i, str(i)) for i in (0, 110, 220, 330)]))
    assert len(result["anchors"]) > 4
    assert any(a["route_m"] > 1000 for a in result["anchors"])
    assert result["coverage_met"] or len(result["anchors"]) == 8


def test_action_overflow_is_reported_and_never_deletes_records():
    exp = experiment(2000, taps=[tap(i, str(i)) for i in range(0, 2000, 150)])
    result = selection(exp)
    assert len(result["anchors"]) == 8
    assert any(c["status"] == "budget" and c["entry_ids"] for c in result["deferred"])
    assert len(exp.taps) == 14


def test_history_requires_three_distinct_prior_walks_for_same_dog():
    refs = [ReferenceWalk(walk_id=str(i), pet_id="dog",
                          started_at=datetime(2026, 9, i+1, tzinfo=UTC), median_speed_mps=3)
            for i in range(3)]
    result = selection(experiment(reference_walks=refs))
    assert result["reference_status"] == "available"
    assert result["steps"][0]["reason"] == "profile_change"
    for invalid in ([refs[0]]*3, refs[:2], [r.model_copy(update={"pet_id": "other"}) for r in refs]):
        assert selection(experiment(reference_walks=invalid))["reference_status"] == (
            "insufficient_history")


def test_session_speed_precedes_distance_and_does_not_invent_sniffing():
    result = selection(experiment(holds=[{"progress_m": 300, "duration_s": 40}]))
    assert result["steps"][0]["reason"] == "session_speed"
    assert result["anchors"][0]["entry_ids"] == []


def test_gap_is_not_used_as_interpolated_anchor():
    exp = experiment()
    exp.scenario = exp.scenario.model_copy(update={"faults": ()})
    raw = exp.model_dump(mode="json")
    raw["scenario"]["faults"] = [{"kind": "dropout", "id": "gap", "start_s": 400,
                                   "end_s": 600}]
    result = selection(Experiment.model_validate(raw))
    assert all(not 400 <= a["elapsed_s"] <= 600 for a in result["anchors"])
    assert len({a["block"] for a in result["anchors"]}) == 2
