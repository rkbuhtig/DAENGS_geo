"""Post-walk HOW assembly. Source supports are never unioned into an event span.

This module is loaded by StampTool's record_how adapter after stamp_tool itself
has loaded. No provider calls; selection/writing continue to consume StampTool.
"""

import math
from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from .how_materials import HowPolicy, HowSource, build_how
from .record_envelopes import Contract, RecordEnvelopeSnapshot, RecordRef
from .stamp_tool import RecordStampPolicy, StampTool


class RouteAttachment(Contract):
    record_ref: RecordRef
    client_seq: int = Field(ge=0)


class HowStampSource(Contract):
    schema_version: Literal["record-how-source-v1"] = "record-how-source-v1"
    route: HowSource
    records: RecordEnvelopeSnapshot
    attachments: tuple[RouteAttachment, ...] = ()

    @model_validator(mode="after")
    def scope(self):
        records = {r.ref.key: r for r in self.records.records}
        if any(r.session_id != self.route.session_id for r in records.values()):
            raise ValueError("records and HOW must share one session")
        if any(f.is_mock != self.records.synthetic for f in self.route.fixes):
            raise ValueError("record and route evidence origins disagree")
        fixes = {f.client_seq: f for f in self.route.fixes}
        used = set()
        for link in self.attachments:
            record, fix = records.get(link.record_ref.key), fixes.get(link.client_seq)
            if record is None or record.ref != link.record_ref or fix is None:
                raise ValueError("unknown or stale route attachment")
            if link.record_ref.key in used:
                raise ValueError("duplicate route attachment")
            used.add(link.record_ref.key)
            loc = record.location
            if (loc is None or record.time_basis == "session_fallback"
                    or loc.observation_ref != observation_ref(self.route, fix)
                    or loc.point.lat != fix.lat or loc.point.lng != fix.lng
                    or loc.captured_at != fix.at or record.event_at != fix.at):
                raise ValueError("attachment must retain the exact observed point and time")
        return self


class HowStampPolicy(Contract):
    model_config = ConfigDict(validate_default=True)
    version: Literal["how-stamp-v1"] = "how-stamp-v1"
    record: RecordStampPolicy = Field(default_factory=RecordStampPolicy)
    geometry: HowPolicy = Field(default_factory=HowPolicy)
    turn_near_s: float = Field(default=20, ge=0)
    focus_radius_m: float = Field(default=15, gt=0)
    shape_context_slots: int = Field(default=2, ge=0, le=4)


def observation_ref(route, fix):
    return f"walk-fix:{route.session_id}:{fix.client_seq}"


def _time(value):
    return datetime.fromisoformat(value)


def _run(value):
    return value["chain_index"], value["how_run_index"]


def _inside(seq, material):
    return material["support"]["from_seq"] <= seq <= material["support"]["to_seq"]


def _metres(a, b):
    dx = math.radians((a["lng"] - b["lng"] + 180) % 360 - 180)
    dx *= math.cos(math.radians((a["lat"] + b["lat"]) / 2))
    return 6_371_000 * math.hypot(dx, math.radians(a["lat"] - b["lat"]))


def _can_share(a, b, policy):
    if _run(a["support"]) != _run(b["support"]) or a["kind"] == b["kind"]:
        return False
    if _metres(a["anchor"], b["anchor"]) > policy.focus_radius_m:
        return False
    if "local_stay" in {a["kind"], b["kind"]}:
        stay, other = (a, b) if a["kind"] == "local_stay" else (b, a)
        return _inside(other["anchor"]["client_seq"], stay)
    # A reversal and retracing share the observed pivot, not merely a long support window.
    return a["anchor"]["client_seq"] == b["anchor"]["client_seq"]


def _groups(materials, policy):
    rank = {"retrace": 0, "local_stay": 1, "turn": 2}
    pending = sorted((m for m in materials if m["kind"] in rank),
                     key=lambda m: (rank[m["kind"]], m["anchor"]["at"], m["ref"]["id"]))
    groups = []
    while pending:
        group = [pending.pop(0)]
        for other in list(pending):
            # Pairwise compatibility prevents a chain of overlaps becoming a large scene.
            if all(_can_share(m, other, policy) for m in group):
                group.append(other)
                pending.remove(other)
        groups.append(group)
    return sorted(groups, key=lambda g: (g[0]["anchor"]["at"], g[0]["ref"]["id"]))


def _record_relation(record, seq, material, policy):
    kind = material["kind"]
    if kind in {"local_stay", "retrace"} and _inside(seq, material):
        return {"type": "record_within_observed_support", "basis": "source_sequence",
                "record_offset_s": (record.event_at - _time(
                    material["support"]["started_at"])).total_seconds()}
    if kind == "turn":
        delta = (record.event_at - _time(material["anchor"]["at"])).total_seconds()
        point = record.location.point.model_dump()
        if (abs(delta) <= policy.turn_near_s
                and _metres(point, material["anchor"]) <= policy.focus_radius_m):
            return {"type": "record_near_turn_vertex", "basis": "observed_vertex",
                    "record_minus_vertex_s": delta,
                    "turn_occurrence_time": "not_resolved"}
    return None


def _shape_members(materials, group, seq, scope, policy, audit, stamp_id):
    eligible = []
    for m in materials:
        if m["kind"] != "straight_run" or _run(m["support"]) != scope:
            continue
        support, relation = m["support"], None
        for focus in group:
            pivot = focus["anchor"]["client_seq"]
            if support["to_seq"] == pivot:
                relation = "ends_at_focus_vertex"
            elif support["from_seq"] == pivot:
                relation = "starts_at_focus_vertex"
            elif focus["kind"] == "local_stay" and (
                support["from_seq"] <= focus["support"]["to_seq"]
                and support["to_seq"] >= focus["support"]["from_seq"]
            ):
                relation = "support_overlaps_stay"
            if relation:
                break
        if not group and _inside(seq, m):
            relation = "contains_record_observation"
        if relation:
            eligible.append((m, relation))
    eligible.sort(key=lambda pair: (
        min(abs(pair[0]["support"]["from_seq"] - seq),
            abs(pair[0]["support"]["to_seq"] - seq)), pair[0]["support"]["from_seq"]
    ))
    result = []
    for index, (m, relation) in enumerate(eligible):
        retained = index < policy.shape_context_slots
        audit.append({"pool": "how_shape", "stamp_id": stamp_id, "id": m["ref"]["id"],
                      "reason": "admit" if retained else "context_budget"})
        if retained:
            result.append({"material_ref": m["ref"], "role": "shape_context",
                           "relation": {"type": relation, "basis": "source_geometry"}})
    return result


def compile_how_stamps(raw, policy):
    source = HowStampSource.model_validate(raw)
    catalog = build_how(source.route, policy.geometry)
    materials = catalog["materials"]
    by_id = {m["ref"]["id"]: m for m in materials}
    groups = _groups(materials, policy)
    base = StampTool("record_envelopes", source.records.model_dump(mode="json"),
                     policy.record.model_dump(mode="json"))
    records = {f"stamp:{r.ref.store}:{r.ref.id}": r for r in source.records.records}
    attachments = {a.record_ref.key: a.client_seq for a in source.attachments}
    scopes = {}
    for id_, record in records.items():
        seq = attachments.get(record.ref.key)
        scopes[id_] = next((_run(r) for r in catalog["shape_runs"]
                            if seq is not None and r["from_seq"] <= seq <= r["to_seq"]), None)
    matched, absorbed = {}, set()
    for id_, record in records.items():
        seq, scope = attachments.get(record.ref.key), scopes[id_]
        options = []
        for index, group in enumerate(groups):
            if scope is None or _run(group[0]["support"]) != scope:
                continue
            relations = [(m, _record_relation(record, seq, m, policy)) for m in group]
            direct = [(m, rel) for m, rel in relations if rel]
            if direct:
                distance = min(abs((record.event_at - _time(m["anchor"]["at"])).total_seconds())
                               for m, _ in direct)
                options.append((distance, index, direct))
        if options:
            _, index, direct = min(options, key=lambda o: (o[0], o[1]))
            matched[id_] = index, direct
            absorbed.add(index)

    frames, projections, anchors, audit = [], {}, {}, []
    for ref in base.refs:
        frame, projected = base.resolve(ref), base.project(ref)
        record, scope = records[ref.id], scopes[ref.id]
        seq = attachments.get(record.ref.key)
        # Past record context requires the same accepted HOW run in this adapter.
        allowed = {ref.id} | {id_ for id_, run in scopes.items() if scope is not None and run == scope}
        envelope_ids = {e.id for e in source.records.envelopes
                        if f"stamp:{e.target.record.store}:{e.target.record.id}" in allowed}
        frame["context_envelope_ids"] = [e for e in frame["context_envelope_ids"] if e in envelope_ids]
        projected["context"] = [e for e in projected["context"] if e["id"] in envelope_ids]
        if frame["previous_action_id"] not in allowed:
            frame["previous_action_id"], projected["relations"] = None, []
        group, members = [], []
        if ref.id in matched:
            index, direct = matched[ref.id]
            group = groups[index]
            direct_by_id = {m["ref"]["id"]: rel for m, rel in direct}
            for m in group:
                relation = direct_by_id.get(m["ref"]["id"], {
                    "type": "cofocus_geometry", "basis": "pairwise_focus_match",
                    "event_order": "not_established",
                })
                members.append({"material_ref": m["ref"], "role": "focus_context",
                                "relation": relation})
        if scope is not None:
            members.extend(_shape_members(materials, group, seq, scope, policy, audit, ref.id))
        frame.update({"center": {"kind": "record", "record_ref": frame["record_ref"]},
                      "how_members": members,
                      "route_binding": "accepted_run" if scope is not None else
                      "rejected_or_isolated_fix" if seq is not None else "not_attached"})
        frames.append(frame)
        projections[ref.id], anchors[ref.id] = projected, base.anchor(ref)

    for index, group in enumerate(groups):
        if index in absorbed:
            audit.append({"pool": "how_focus", "id": group[0]["ref"]["id"],
                          "reason": "attached_to_record"})
            continue
        focus = group[0]
        id_ = "stamp:" + focus["ref"]["id"]
        members = [{"material_ref": m["ref"], "role": "focus" if m is focus else "cofocus",
                    "relation": {"type": "focus_geometry", "event_order": "not_established"}}
                   for m in group]
        members.extend(_shape_members(materials, group, focus["anchor"]["client_seq"],
                                      _run(focus["support"]), policy, audit, id_))
        frames.append({"id": id_, "required": False,
                       "center": {"kind": "how", "material_ref": focus["ref"]},
                       "how_members": members, "route_binding": "accepted_run"})
        anchor = focus["anchor"]
        anchors[id_] = {"session_id": source.route.session_id, "event_at": anchor["at"],
                        "time_basis": "geometry_representative_observation",
                        "location": {"point": {k: anchor[k] for k in ("lat", "lng")},
                                     "observation_ref": observation_ref(source.route,
                                         next(f for f in source.route.fixes
                                              if f.client_seq == anchor["client_seq"]))}}
        projections[id_] = {"id": id_, "tag": "movement_focus",
                            "when": {"event_at": anchor["at"],
                                     "basis": "representative_observation_not_event_onset"},
                            "context": [], "relations": []}

    for frame in frames:
        id_ = frame["id"]
        # No union span is created. Each member retains its complete original support.
        how = []
        for member in frame["how_members"]:
            m = by_id[member["material_ref"]["id"]]
            how.append({**member, **{k: m[k] for k in (
                "kind", "status", "subject", "support", "metrics", "quality"
            )}})
        projections[id_].update({"mode": "post_walk", "how": how,
                                 "how_limits": catalog["limits"],
                                 "route_binding": frame["route_binding"],
                                 "available_at": max([anchors[id_]["event_at"]]
                                     + [h["support"]["ended_at"] for h in how], key=_time)})
    frames.sort(key=lambda f: (_time(anchors[f["id"]]["event_at"]), f["id"]))
    return {"frames": frames, "projections": projections, "anchors": anchors,
            "catalog": catalog, "audit": {"record": base.dump()["slot_audit"], "how": audit}}
