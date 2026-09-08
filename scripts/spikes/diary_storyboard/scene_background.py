"""One saved-envelope/trajectory assembler for either origin of scene centre.

It returns background and relations only. Core actions are not writable here.
Envelope.targets bind a versioned core before the final stamp is generated.
"""

import math
from copy import deepcopy
from datetime import datetime

from pydantic import AwareDatetime, ConfigDict, Field

from .record_envelopes import Contract, Envelope, Point
from .stamp_tool import StampRef, _project_envelope, _Slots


class BackgroundTarget(Contract):
    core_ref: StampRef
    session_id: str = Field(min_length=1)
    event_at: AwareDatetime
    point: Point | None
    radius_m: float | None = Field(default=None, gt=0)


class BackgroundEnvelope(Envelope):
    # Parent validation preserves payload hashes, missing/partial states and
    # event-weather validity, without requiring a user-record target.
    target: BackgroundTarget


class BackgroundPolicy(Contract):
    model_config = ConfigDict(validate_default=True)
    space_slots: int = Field(default=3, ge=1)
    environment_slots: int = Field(default=1, ge=1)
    trajectory_slots: int = Field(default=2, ge=0)
    context_age_s: int = Field(default=300, ge=0)
    prior_record_age_s: int = Field(default=600, ge=0)
    turn_near_s: float = Field(default=20, ge=0)
    turn_near_m: float = Field(default=15, gt=0)


def target_for(core, *, radius_m=None):
    return BackgroundTarget(
        core_ref=core["ref"], session_id=core["session_id"], event_at=core["event_at"],
        point=core["location"]["point"] if core["location"] else None, radius_m=radius_m,
    )


def validate_envelopes(cores, envelopes, selected_ids, *, synthetic):
    by_core = {c["id"]: c for c in cores}
    by_id, scopes = {}, set()
    for envelope in envelopes:
        core = by_core.get(envelope.target.core_ref.id)
        if core is None or envelope.target != target_for(core, radius_m=envelope.target.radius_m):
            raise ValueError("background target changes core reference, session, time or location")
        if envelope.provenance.synthetic != synthetic:
            raise ValueError("background evidence origin differs from source")
        if envelope.id in by_id:
            raise ValueError("duplicate background envelope ID")
        if envelope.supersedes:
            previous = by_id.get(envelope.supersedes)
            if (previous is None or previous.target != envelope.target
                    or set(previous.tags) != set(envelope.tags)
                    or previous.provenance.provider != envelope.provenance.provider
                    or previous.provenance.operation != envelope.provenance.operation):
                raise ValueError("replacement needs the same background query scope")
        by_id[envelope.id] = envelope
    if len(selected_ids) != len(set(selected_ids)) or not set(selected_ids) <= by_id.keys():
        raise ValueError("duplicate or unknown selected background")
    for eid in selected_ids:
        envelope = by_id[eid]
        t = envelope.target
        scope = (t.core_ref.id, t.core_ref.version, t.radius_m, tuple(sorted(envelope.tags)),
                 envelope.provenance.provider, envelope.provenance.operation)
        if scope in scopes:
            raise ValueError("multiple selected results for one background query")
        scopes.add(scope)
    return by_id


def _metres(a, b):
    dx = math.radians((a["lng"] - b["lng"] + 180) % 360 - 180)
    dx *= math.cos(math.radians((a["lat"] + b["lat"]) / 2))
    return 6_371_000 * math.hypot(dx, math.radians(a["lat"] - b["lat"]))


def _trajectory(core, binding, materials, policy, audit):
    eligible = []
    if binding["status"] != "accepted_run":
        return []
    seq, scope = binding["client_seq"], binding["scope"]
    for m in materials:
        s = m["support"]
        if ([s["chain_index"], s["how_run_index"]] != scope
                or m["ref"] in binding.get("exclude_refs", [])):
            continue
        relation = None
        if m["kind"] == "turn":
            delta = (datetime.fromisoformat(core["event_at"])
                     - datetime.fromisoformat(m["anchor"]["at"])).total_seconds()
            if (abs(delta) <= policy.turn_near_s
                    and _metres(core["location"]["point"], m["anchor"]) <= policy.turn_near_m):
                relation = {"type": "near_observed_turn_vertex", "record_minus_vertex_s": delta,
                            "turn_occurrence_time": "not_resolved"}
        elif s["from_seq"] <= seq <= s["to_seq"]:
            relation = {"type": "anchor_within_observed_support", "basis": "source_sequence"}
        if relation:
            eligible.append((m, relation))
    eligible.sort(key=lambda pair: (pair[0]["kind"] == "straight_run",
                                   pair[0]["support"]["window_s"], pair[0]["ref"]["id"]))
    result = []
    for index, (m, relation) in enumerate(eligible):
        kept = index < policy.trajectory_slots
        audit.append({"pool": "trajectory", "core_id": core["id"], "id": m["ref"]["id"],
                      "reason": "admit" if kept else "capacity"})
        if kept:
            result.append({"material_ref": m["ref"], "role": "trajectory_context",
                           "relation": relation, **{k: m[k] for k in (
                               "kind", "subject", "status", "support", "metrics", "quality")}})
    return result


def assemble_backgrounds(cores, bindings, catalog, envelopes, selected_ids, policy, *, synthetic):
    cores = deepcopy(cores)
    by_id = validate_envelopes(cores, envelopes, selected_ids, synthetic=synthetic)
    selected = [by_id[eid] for eid in selected_ids]
    result, audit, previous_records = {}, [], []
    slots = {domain: _Slots(domain, capacity, policy.context_age_s, audit) for domain, capacity in (
        ("space", policy.space_slots), ("environment", policy.environment_slots))}
    for core in sorted(cores, key=lambda c: (datetime.fromisoformat(c["event_at"]), c["id"])):
        binding = bindings[core["id"]]
        at = datetime.fromisoformat(core["event_at"]).timestamp()
        # Unbound records may have their own spatial query; prior spatial context
        # needs the same accepted run. A session-wide note cannot carry it onward.
        scope = ((core["session_id"], tuple(binding["scope"]))
                 if binding["status"] == "accepted_run" else (core["session_id"], core["id"]))
        current = [e for e in selected if e.target.core_ref.id == core["id"]]
        for domain, pool in slots.items():
            pool.advance(at, scope)
            for e in current:
                if any(tag.startswith(domain + ".") for tag in e.tags):
                    pool.put(e.id, at, scope)
        background = {"space": [], "environment": [], "trajectory": [], "other": [],
                      "route_binding": binding["status"], "current_query_status": {}}
        resident = set().union(*(set(pool.items) for pool in slots.values()))
        for eid in sorted(resident | {e.id for e in current}):
            e = by_id[eid]
            direct = e.target.core_ref.id == core["id"]
            projected = _project_envelope(e)
            if "relation_basis" in projected:
                projected["relation_basis"] = "distance_to_reference_at_target_anchor"
            projected.update({"applies_to_core": e.target.core_ref.model_dump(mode="json"),
                              "relation_to_stamp": "same_core" if direct else "prior_core_query",
                              "retrieved_at": e.provenance.retrieved_at.isoformat()
                              if e.provenance.retrieved_at else None,
                              "elapsed_s": at - e.target.event_at.timestamp()})
            domains = [d for d in slots if any(t.startswith(d + ".") for t in e.tags)] or ["other"]
            for domain in domains:
                background[domain].append(deepcopy(projected))
        for domain in slots:
            direct = [e.status for e in current if any(t.startswith(domain + ".") for t in e.tags)]
            background["current_query_status"][domain] = sorted(set(direct)) or ["not_requested"]
        background["trajectory"] = _trajectory(core, binding, catalog["materials"] if catalog else [],
                                               policy, audit)
        relations = []
        if binding["status"] == "accepted_run":
            prior = next((c for c in reversed(previous_records)
                          if bindings[c["id"]].get("scope") == binding["scope"]
                          and 0 <= at - datetime.fromisoformat(c["event_at"]).timestamp()
                          <= policy.prior_record_age_s), None)
            if prior:
                relations.append({"type": "after_user_record", "from_core": prior["ref"],
                                  "elapsed_s": at - datetime.fromisoformat(prior["event_at"]).timestamp(),
                                  "basis": "record_timestamp_difference",
                                  "continuous_presence": "not_established"})
        if core["origin"] == "user_record" and core["time_basis"] != "session_fallback":
            previous_records.append(core)
        result[core["id"]] = {"background": background, "relations": relations}
    return deepcopy(result), deepcopy(audit)
