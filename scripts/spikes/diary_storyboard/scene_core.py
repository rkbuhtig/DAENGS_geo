"""Scene centres and supplementation. No route analysis, background lookup or LLM."""

from copy import deepcopy
from datetime import datetime, timedelta

from pydantic import ConfigDict, Field

from .record_envelopes import Contract, Record, payload_hash


class SupplementPolicy(Contract):
    model_config = ConfigDict(validate_default=True)
    target_scene_count: int = Field(ge=0, le=20)
    separation_s: float = Field(default=20, ge=0)


def _freeze_ref(core):
    return {**deepcopy(core), "ref": {"id": core["id"], "version": payload_hash(core)}}


def user_cores(raw):
    records = [Record.model_validate(r) for r in raw]
    if len({r.session_id for r in records}) > 1 or len({r.owner_id for r in records}) > 1:
        raise ValueError("scene cores need one session")
    if len({r.ref.key for r in records}) != len(records):
        raise ValueError("scene cores need unique original records")
    result = []
    for record in sorted(records, key=lambda r: (r.event_at, r.ref.key)):
        ref = record.ref.model_dump(mode="json")
        result.append(_freeze_ref({
            "id": f"stamp:{record.ref.store}:{record.ref.id}", "origin": "user_record",
            "session_id": record.session_id, "event_at": record.event_at.isoformat(),
            "time_basis": record.time_basis,
            "location": record.location.model_dump(mode="json") if record.location else None,
            "action": {"origin": "user_record", "record_ref": ref,
                       "content": record.content.model_dump(mode="json"),
                       "when": {"event_at": record.event_at.isoformat(), "basis": record.time_basis}},
        }))
    return result


def observation_core(session_id, candidate):
    anchor = candidate["anchor"]
    return _freeze_ref({
        "id": "stamp:" + candidate["ref"]["id"], "origin": "derived_observation",
        "session_id": session_id, "event_at": anchor["at"],
        "time_basis": "observation_representative_not_action_onset",
        "location": {"point": {k: anchor[k] for k in ("lat", "lng")},
                     "observation_ref": f"walk-fix:{session_id}:{anchor['client_seq']}"},
        "action": {"candidate_ref": candidate["ref"], **{k: candidate[k] for k in (
            "origin", "status", "subject", "kind", "action_meaning", "support", "metrics"
        )}},
    })


def choose_supplements(cores, candidates, policy):
    """Preserve v1 choice rules; returns references/audit, never edits either pool."""
    if any(c["origin"] != "user_record" for c in cores):
        raise ValueError("deficit must be measured from user-centred scenes")
    deficit = max(0, policy.target_scene_count - len(cores))
    margin = timedelta(seconds=policy.separation_s)
    selected, decisions = [], []

    def window(candidate):
        return tuple(datetime.fromisoformat(candidate["support"][k])
                     for k in ("started_at", "ended_at"))

    pending = sorted(candidates, key=lambda c: (
        0 if c["kind"] == "observed_dwell" else 1,
        -c["support"]["window_s"], c["anchor"]["at"], c["ref"]["id"],
    ))
    for candidate in pending:
        start, end = window(candidate)
        if not deficit:
            reason = "user_target_met"
        elif any(start - margin <= datetime.fromisoformat(c["event_at"]) <= end + margin
                 for c in cores if c["time_basis"] != "session_fallback"):
            reason = "near_user_record_time"
        elif any(start <= window(c)[1] + margin and end >= window(c)[0] - margin for c in selected):
            reason = "overlapping_selected_observation"
        elif len(selected) >= deficit:
            reason = "deficit_filled"
        else:
            selected.append(candidate)
            reason = "fill_scene_deficit"
        decisions.append({"candidate_ref": candidate["ref"], "reason": reason})
    return deepcopy({
        "selected_refs": [c["ref"] for c in selected], "decisions": decisions,
        "scene_counts": {"basis": "one_stamp_per_user_record_before_editorial_grouping",
                         "target": policy.target_scene_count, "user_records": len(cores),
                         "initial_deficit": deficit, "supplemented": len(selected),
                         "remaining_deficit": deficit - len(selected)},
    })
