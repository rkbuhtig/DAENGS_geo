"""Prepare centres/query targets, then freeze saved background into stamps.

The v2 path never calls compile_how_stamps or the earlier stamp assemblers.
The outer runner can collect background between prepare_scene_plan and StampTool.
"""

from copy import deepcopy
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .action_candidates import ActionCandidatePolicy, build_action_candidates
from .how_materials import HowPolicy, HowSource, build_how
from .record_envelopes import Contract, RecordEnvelopeSnapshot, RecordRef
from .scene_background import (
    BackgroundEnvelope,
    BackgroundPolicy,
    assemble_backgrounds,
    target_for,
)
from .scene_core import SupplementPolicy, choose_supplements, observation_core, user_cores


class SceneRouteAttachment(Contract):
    record_ref: RecordRef
    client_seq: int = Field(ge=0)


class SceneSource(Contract):
    schema_version: Literal["scene-source-v2"] = "scene-source-v2"
    session_id: str = Field(min_length=1)
    records: RecordEnvelopeSnapshot
    route: HowSource | None = None
    route_status: Literal["ready", "unavailable", "not_requested"] = "not_requested"
    route_reason: str | None = None
    attachments: tuple[SceneRouteAttachment, ...] = ()
    background_envelopes: tuple[BackgroundEnvelope, ...] = ()
    selected_background_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def scope(self):
        records = {r.ref.key: r for r in self.records.records}
        if any(r.session_id != self.session_id for r in records.values()):
            raise ValueError("record crosses scene session")
        if self.route_status == "ready" and self.route is None:
            raise ValueError("ready route needs its source")
        if self.route_status == "unavailable" and not self.route_reason:
            raise ValueError("unavailable route needs a reason")
        if self.route is None:
            if self.attachments:
                raise ValueError("route attachments need an observed source")
            return self
        if (self.route.session_id != self.session_id
                or any(f.is_mock != self.records.synthetic for f in self.route.fixes)):
            raise ValueError("route session or evidence origin mismatch")
        fixes, used = {f.client_seq: f for f in self.route.fixes}, set()
        for attachment in self.attachments:
            record, fix = records.get(attachment.record_ref.key), fixes.get(attachment.client_seq)
            if (record is None or record.ref != attachment.record_ref or fix is None
                    or attachment.record_ref.key in used):
                raise ValueError("unknown, stale or duplicate route attachment")
            used.add(attachment.record_ref.key)
            loc = record.location
            if (loc is None or record.time_basis == "session_fallback"
                    or loc.observation_ref != f"walk-fix:{self.session_id}:{fix.client_seq}"
                    or loc.point.lat != fix.lat or loc.point.lng != fix.lng
                    or loc.captured_at != fix.at or record.event_at != fix.at):
                raise ValueError("route attachment must keep the exact observed point and time")
        return self


class ScenePolicy(SupplementPolicy):
    version: Literal["action-background-v2"] = "action-background-v2"
    max_cards: int = Field(default=7, ge=1)
    geometry: HowPolicy = Field(default_factory=HowPolicy)
    candidates: ActionCandidatePolicy = Field(default_factory=ActionCandidatePolicy)
    background: BackgroundPolicy = Field(default_factory=BackgroundPolicy)

    @model_validator(mode="after")
    def capacity(self):
        if self.target_scene_count > self.max_cards:
            raise ValueError("target must fit explicit card capacity")
        return self


def source_from_how(raw):
    """Explicit source migration, without executing the archived HOW assembler."""
    return SceneSource.model_validate({
        "session_id": raw["route"]["session_id"], "records": raw["records"],
        "route": raw["route"], "route_status": "ready", "attachments": raw.get("attachments", []),
    }).model_dump(mode="json")


def _binding(seq, catalog, status):
    if catalog is None:
        return {"status": f"route_{status}"}
    run = next((r for r in catalog["shape_runs"]
                if seq is not None and r["from_seq"] <= seq <= r["to_seq"]), None)
    if run is None:
        return {"status": "not_attached" if seq is None else "rejected_or_isolated_fix"}
    return {"status": "accepted_run", "client_seq": seq,
            "scope": [run["chain_index"], run["how_run_index"]]}


def prepare_scene_plan(raw, policy):
    source = SceneSource.model_validate(raw)
    policy = ScenePolicy.model_validate(policy)
    cores = user_cores(source.records.records)  # Deliberately before optional motion analysis.
    catalog, pool = None, {"candidates": []}
    status, reason = source.route_status, source.route_reason
    if status == "ready":
        try:
            catalog = build_how(source.route, policy.geometry)
            pool = build_action_candidates(source.route, catalog, policy.candidates)
        except RuntimeError:
            # Recover an unavailable calculation stage; invalid/stale source
            # contracts (ValueError) still fail rather than silently changing facts.
            catalog, pool = None, {"candidates": []}
            status, reason = "unavailable", "motion_calculation_failed"
    links = {a.record_ref.key: a.client_seq for a in source.attachments}
    bindings = {}
    for core in cores:
        ref = RecordRef.model_validate(core["action"]["record_ref"])
        bindings[core["id"]] = _binding(links.get(ref.key), catalog, status)
    selection = choose_supplements(cores, pool["candidates"], policy)
    by_candidate = {c["ref"]["id"]: c for c in pool["candidates"]}
    for ref in selection["selected_refs"]:
        candidate = by_candidate[ref["id"]]
        core = observation_core(source.session_id, candidate)
        binding = _binding(candidate["anchor"]["client_seq"], catalog, status)
        binding["exclude_refs"] = ([candidate["source_material_ref"]]
                                   if "source_material_ref" in candidate else [])
        cores.append(core)
        bindings[core["id"]] = binding
    cores.sort(key=lambda c: (datetime.fromisoformat(c["event_at"]), c["id"]))
    return deepcopy({"schema_version": "scene-plan-v2", "cores": cores, "bindings": bindings,
                     "motion": {"status": status, "reason": reason, "catalog": catalog, "pool": pool},
                     "selection": selection})


def background_requests(plan, *, radius_m=100):
    """Declarative requests for an outer collector; no HTTP or provider side effects."""
    requests = []
    for core in plan["cores"]:
        located = core["location"] is not None and core["time_basis"] != "session_fallback"
        for domain in ("space", "environment"):
            target = target_for(core, radius_m=radius_m if located and domain == "space" else None)
            requests.append({"domain": domain, "target": target.model_dump(mode="json"),
                             "status": "planned" if located else "not_requested",
                             "reason": None if located else "no_observed_event_location"})
    return requests


def _saved_envelopes(source, cores):
    # Adapt existing record-bound saved queries without assigning them to another
    # core. Both old saved queries and new observation queries then use one path.
    by_record = {(c["action"]["record_ref"]["store"], c["action"]["record_ref"]["id"]): c
                 for c in cores if c["origin"] == "user_record"}
    envelopes = []
    for envelope in source.records.envelopes:
        core = by_record[envelope.target.record.key]
        value = envelope.model_dump(mode="json")
        value["target"] = target_for(core, radius_m=envelope.target.radius_m).model_dump(mode="json")
        envelopes.append(BackgroundEnvelope.model_validate(value))
    envelopes.extend(source.background_envelopes)
    return envelopes, list(source.records.selected_envelope_ids) + list(source.selected_background_ids)


def compile_scene_stamps(raw, policy):
    source = SceneSource.model_validate(raw)
    plan = prepare_scene_plan(source, policy)
    cores, bindings, motion = plan["cores"], plan["bindings"], plan["motion"]
    envelopes, selected = _saved_envelopes(source, cores)
    assembled, audit = assemble_backgrounds(
        cores, bindings, motion["catalog"], envelopes, selected, policy.background,
        synthetic=(source.records.context_mode == "synthetic"),
    )
    frames, projections, anchors = [], {}, {}
    for core in cores:
        id_, content = core["id"], assembled[core["id"]]
        frames.append({"id": id_, "core_ref": core["ref"], "required": True,
                       "selection_basis": "user_record" if core["origin"] == "user_record"
                       else "scene_deficit_policy"})
        support_ends = [m["support"]["ended_at"] for m in content["background"]["trajectory"]]
        query_times = [e["retrieved_at"] for domain in ("space", "environment", "other")
                       for e in content["background"][domain] if e["retrieved_at"]]
        projections[id_] = {
            "id": id_, "tag": "action_with_background", "mode": "post_walk",
            "action": deepcopy(core["action"]), **content,
            "available_at": max([core["event_at"]] + support_ends + query_times
                                + ([motion["pool"]["available_at"]]
                                   if core["origin"] == "derived_observation" else []),
                                key=datetime.fromisoformat),
        }
        anchors[id_] = {k: deepcopy(core[k]) for k in (
            "session_id", "event_at", "time_basis", "location", "origin")}
        anchors[id_]["core_ref"] = core["ref"]
    frozen_source = source.model_dump(mode="json")
    # Books written before the provider collector had no context_mode field.
    # Preserve that representation so a default does not silently reversion them.
    if isinstance(raw, dict) and "context_mode" not in raw["records"]:
        frozen_source["records"].pop("context_mode")
    # A transient calculation failure must remain replayable after recovery.
    # Freeze the stage outcome along with the unchanged raw route/records.
    frozen_source.update(route_status=motion["status"], route_reason=motion["reason"])
    return {"frames": frames, "projections": projections, "anchors": anchors,
            "frozen_source": frozen_source, "plan": plan,
            "audit": {"background": audit, **plan["selection"]}}
