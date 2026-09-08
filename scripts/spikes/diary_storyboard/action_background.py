"""User action first; separately attach background and fill only a scene deficit."""

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from .action_candidates import ActionCandidatePolicy, build_action_candidates
from .how_stamps import HowStampPolicy, HowStampSource, compile_how_stamps
from .record_envelopes import Contract


class ActionBackgroundPolicy(Contract):
    model_config = ConfigDict(validate_default=True)
    version: Literal["action-background-v1"] = "action-background-v1"
    target_scene_count: int = Field(ge=0, le=20)  # Explicit caller choice, no product default.
    background: HowStampPolicy = Field(default_factory=HowStampPolicy)
    candidates: ActionCandidatePolicy = Field(default_factory=ActionCandidatePolicy)
    separation_s: float = Field(default=20, ge=0)

    @model_validator(mode="after")
    def capacity(self):
        if self.target_scene_count > self.background.record.max_cards:
            raise ValueError("target must fit the explicit card capacity")
        return self


def _time(value):
    return datetime.fromisoformat(value)


def _window(candidate):
    return tuple(_time(candidate["support"][k]) for k in ("started_at", "ended_at"))


def _background(projected):
    return {
        "context": projected["context"],
        "trajectory": [{**h, "role": "trajectory_context"} for h in projected["how"]],
        "route_binding": projected["route_binding"],
        "limits": projected["how_limits"],
    }


def compile_action_background(raw, policy):
    source = HowStampSource.model_validate(raw)
    assembled = compile_how_stamps(raw, policy.background)
    catalog = assembled["catalog"]
    pool = build_action_candidates(source.route, catalog, policy.candidates)
    frames, projections, anchors = [], {}, {}
    for old in assembled["frames"]:
        if old["center"]["kind"] != "record":
            continue  # Ordinary geometry no longer opens its own action scene.
        id_ = old["id"]
        projected = assembled["projections"][id_]
        background = _background(projected)
        frames.append({
            "id": id_, "required": True, "selection_basis": "user_record",
            "action": {"origin": "user_record", "record_ref": old["record_ref"]},
            "background_refs": {"envelopes": old["context_envelope_ids"],
                                "trajectory": [h["material_ref"] for h in projected["how"]]},
        })
        projections[id_] = {
            "id": id_, "tag": "action_with_background", "mode": "post_walk",
            "action": {"origin": "user_record", "record_ref": old["record_ref"],
                       "content": projected["record"], "when": projected["when"]},
            "background": background, "relations": projected["relations"],
            "available_at": projected["available_at"],
        }
        anchors[id_] = assembled["anchors"][id_]

    user_count = len(frames)
    deficit = max(0, policy.target_scene_count - user_count)
    margin = timedelta(seconds=policy.separation_s)
    selected, decisions = [], []
    # Provisional editorial tie-break: dwell, then pace; longer evidence first.
    pending = sorted(pool["candidates"], key=lambda c: (
        0 if c["kind"] == "observed_dwell" else 1,
        -c["support"]["window_s"], c["anchor"]["at"], c["ref"]["id"],
    ))
    for candidate in pending:
        start, end = _window(candidate)
        reason = None
        if not deficit:
            reason = "user_target_met"
        elif any(start - margin <= r.event_at <= end + margin for r in source.records.records
                 if r.time_basis != "session_fallback"):
            # Editorial time proximity, not a claim of co-location or action duration.
            reason = "near_user_record_time"
        elif any(start <= _window(other)[1] + margin and end >= _window(other)[0] - margin
                 for other in selected):
            reason = "overlapping_selected_observation"
        elif len(selected) >= deficit:
            reason = "deficit_filled"
        else:
            selected.append(candidate)
            reason = "fill_scene_deficit"
        decisions.append({"candidate_ref": candidate["ref"], "reason": reason})

    for candidate in selected:
        id_ = "stamp:" + candidate["ref"]["id"]
        anchor, support = candidate["anchor"], candidate["support"]
        members = [m for m in catalog["materials"]
                   if m["ref"] != candidate.get("source_material_ref")
                   and all(m["support"][k] == support[k]
                           for k in ("chain_index", "how_run_index"))
                   and m["support"]["from_seq"] <= anchor["client_seq"] <= m["support"]["to_seq"]]
        members.sort(key=lambda m: (m["support"]["window_s"], m["ref"]["id"]))
        members = members[:policy.background.shape_context_slots]
        frames.append({
            "id": id_, "required": True, "selection_basis": "scene_deficit_policy",
            "action": {"origin": "derived_observation", "candidate_ref": candidate["ref"]},
            "background_refs": {"envelopes": [], "trajectory": [m["ref"] for m in members]},
        })
        projections[id_] = {
            "id": id_, "tag": "action_with_background", "mode": "post_walk",
            "action": {"candidate_ref": candidate["ref"], **{k: candidate[k] for k in (
                "origin", "status", "subject", "kind", "action_meaning", "support", "metrics"
            )}},
            "background": {
                # Current envelopes target user records. Never retarget that lookup
                # to a derived observation merely because it is the nearest scene.
                "context": [], "context_status": "not_requested_for_observation",
                "trajectory": [{"material_ref": m["ref"], "role": "trajectory_context",
                                "relation": {"type": "anchor_within_observed_support"},
                                **{k: m[k] for k in ("kind", "subject", "support", "metrics")}}
                               for m in members],
                "route_binding": "accepted_run", "limits": catalog["limits"],
            },
            "relations": [], "available_at": pool["available_at"],
        }
        anchors[id_] = {
            "session_id": source.route.session_id, "event_at": anchor["at"],
            "time_basis": "observation_representative_not_action_onset",
            "origin": "derived_observation", "candidate_ref": candidate["ref"],
            "location": {"point": {k: anchor[k] for k in ("lat", "lng")},
                         "observation_ref": f"walk-fix:{source.route.session_id}:{anchor['client_seq']}"},
        }
    frames.sort(key=lambda f: (_time(anchors[f["id"]]["event_at"]), f["id"]))
    return deepcopy({
        "frames": frames, "projections": projections, "anchors": anchors, "catalog": catalog,
        "derived_action_catalog": pool,
        "audit": {"background": assembled["audit"], "action_selection": decisions,
                  "scene_counts": {"basis": "one_stamp_per_user_record_before_editorial_grouping",
                                   "target": policy.target_scene_count, "user_records": user_count,
                                   "initial_deficit": deficit, "supplemented": len(selected),
                                   "remaining_deficit": deficit - len(selected)}},
    })
