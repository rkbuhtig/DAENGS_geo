"""Compile frozen sources into stamps; no model, network, database or card text.

The public boundary is compile -> query/resolve -> dump/load. Slot replacement is
internal, and a changed source or policy produces new stamp versions. The archive
adapter remains a replay bridge, not a parser for new user records.
"""

import json
from collections import OrderedDict
from copy import deepcopy
from typing import Literal

from pydantic import Field

from .record_envelopes import Contract, RecordEnvelopeSnapshot, payload_hash


class StampRef(Contract):
    id: str = Field(min_length=1)
    version: str = Field(pattern=r"^[0-9a-f]{64}$")


class RecordStampPolicy(Contract):
    version: Literal["record-stamp-v1"] = "record-stamp-v1"
    space_slots: int = Field(default=3, ge=1)
    action_slots: int = Field(default=2, ge=1)
    environment_slots: int = Field(default=1, ge=1)
    context_age_s: int = Field(default=300, ge=0)
    action_age_s: int = Field(default=600, ge=0)
    max_cards: int = Field(default=7, ge=1)


class _Slots:
    """Only source IDs reside in slots. Removing one never removes its source."""

    def __init__(self, name, capacity, age_s, audit):
        self.name, self.capacity, self.age_s = name, capacity, age_s
        self.items, self.audit = OrderedDict(), audit

    def _remove(self, key, at, reason):
        self.items.pop(key)
        self.audit.append({"pool": self.name, "id": key, "at": at, "reason": reason})

    def advance(self, at, session):
        for key, (seen, scope) in list(self.items.items()):
            if scope != session:
                self._remove(key, at, "session_reset")
            elif at - seen > self.age_s:
                self._remove(key, at, "expired")

    def put(self, key, at, session):
        self.items.pop(key, None)
        self.items[key] = (at, session)
        self.audit.append({"pool": self.name, "id": key, "at": at, "reason": "admit"})
        if len(self.items) > self.capacity:
            self._remove(next(iter(self.items)), at, "capacity_eviction")


def _record_id(record):
    return f"stamp:{record.ref.store}:{record.ref.id}"


def _record_frames(source, policy):
    snapshot = RecordEnvelopeSnapshot.model_validate(source)
    if len({r.session_id for r in snapshot.records}) > 1:
        raise ValueError("stamp tool needs one walk session")
    records = sorted(snapshot.records, key=lambda r: (r.event_at, _record_id(r)))
    selected = set(snapshot.selected_envelope_ids)
    envelopes = [e for e in snapshot.envelopes if e.id in selected]
    audit, frames = [], []
    pools = {
        "space": _Slots("space", policy.space_slots, policy.context_age_s, audit),
        "action": _Slots("action", policy.action_slots, policy.action_age_s, audit),
        "environment": _Slots(
            "environment", policy.environment_slots, policy.context_age_s, audit
        ),
    }
    for record in records:
        at, session = record.event_at.timestamp(), record.session_id
        for pool in pools.values():
            pool.advance(at, session)
        current = [e for e in envelopes if e.target.record == record.ref]
        for envelope in current:
            # Unavailable/empty results are evidence of query status, not a place.
            for domain in ("space", "environment"):
                if any(t.startswith(domain + ".") for t in envelope.tags):
                    pools[domain].put(envelope.id, at, session)
        previous = next(reversed(pools["action"].items), None)
        resident = set(pools["space"].items) | set(pools["environment"].items)
        # Exact-target envelopes survive a slot budget: the budget bounds *past*
        # context. movement.window is retained here even without a projector yet.
        context = resident | {e.id for e in current}
        if record.time_basis == "session_fallback":
            context, previous = {e.id for e in current}, None
        frames.append({
            "id": _record_id(record),
            "required": True,
            "record_ref": record.ref.model_dump(mode="json"),
            "context_envelope_ids": sorted(context),
            "previous_action_id": previous,
        })
        if record.content.kind in {"behavior", "photo"}:
            pools["action"].put(_record_id(record), at, session)
    return frames, audit


def _project_envelope(envelope):
    """A deliberately finite synthetic projector. Unknown provider JSON stays out."""
    result = {
        "id": envelope.id, "tags": list(envelope.tags), "status": envelope.status,
        "temporal_basis": envelope.provenance.temporal_basis,
        "projection_status": "not_supported",
    }
    if envelope.reason:
        result["reason"] = envelope.reason
    if envelope.status in {"unavailable", "not_requested"}:
        result["projection_status"] = "no_payload"
        return result
    if not (envelope.provenance.synthetic
            and envelope.provenance.provider == "synthetic-provider"
            and envelope.payload_format == "synthetic-provider-response-v1"):
        return result
    payload = envelope.payload
    if set(envelope.tags) == {"environment.weather"}:
        if envelope.provenance.temporal_basis != "event_observation":
            result["projection_status"] = "not_event_weather"
            return result
        result["measurements"] = {
            k: payload[k] for k in ("temperature_c", "precipitation_mm") if k in payload
        }
        result["valid_time"] = envelope.provenance.valid_time.model_dump(mode="json")
    elif set(envelope.tags) <= {"space.park", "space.river", "space.facility"}:
        rows = payload.get("features", payload.get("results", []))
        result["features"] = [
            {k: row[k] for k in ("id", "name", "category", "distance_m", "geometry_reference")
             if k in row} for row in rows[:3]
        ]
        result["omitted_from_projection"] = max(0, len(rows) - 3)
        result["relation_basis"] = "distance_to_reference_at_target_record"
        result["query_radius_m"] = envelope.target.radius_m
        result["coverage"] = "partial" if envelope.status == "partial" else "query_only"
    else:
        return result
    result["projection_status"] = "projected"
    return result


class StampTool:
    """One frozen source scope. Accessors return copies; load checks deterministic replay.

    record-v1 emits one stamp per original record (all required). record_how
    additionally assembles post-walk geometry, preserving each original support.
    action_background separates user/derived actions and supplements a deficit.
    """

    def __init__(self, kind, source, policy=None):
        self._source = json.dumps(source, ensure_ascii=False, allow_nan=False)
        source = json.loads(self._source)
        self._kind = kind
        self._source_version = payload_hash(source)
        if kind == "record_envelopes":
            p = RecordStampPolicy.model_validate(policy or {})
            self._policy = p.model_dump(mode="json")
            self._frames, self._audit = _record_frames(source, p)
            snapshot = RecordEnvelopeSnapshot.model_validate(source)
            self._records = {_record_id(r): r for r in snapshot.records}
            self._envelopes = {e.id: e for e in snapshot.envelopes}
            self._max_cards = p.max_cards
            self._actors = []
        elif kind == "record_how":
            from .how_stamps import HowStampPolicy, compile_how_stamps

            p = HowStampPolicy.model_validate(policy or {})
            self._policy = p.model_dump(mode="json")
            self._compiled = compile_how_stamps(source, p)
            self._frames, self._audit = self._compiled["frames"], self._compiled["audit"]
            self._max_cards, self._actors = p.record.max_cards, []
        elif kind == "action_background":
            from .action_background import ActionBackgroundPolicy, compile_action_background

            p = ActionBackgroundPolicy.model_validate(policy or {})
            self._policy = p.model_dump(mode="json")
            self._compiled = compile_action_background(source, p)
            self._frames, self._audit = self._compiled["frames"], self._compiled["audit"]
            self._max_cards, self._actors = p.background.record.max_cards, []
        elif kind == "action_background_v2":
            from .scene_pipeline import ScenePolicy, compile_scene_stamps

            p = ScenePolicy.model_validate(policy or {})
            self._policy = p.model_dump(mode="json")
            self._compiled = compile_scene_stamps(source, p)
            self._source = json.dumps(self._compiled["frozen_source"], ensure_ascii=False,
                                      allow_nan=False)
            self._source_version = payload_hash(self._compiled["frozen_source"])
            self._frames, self._audit = self._compiled["frames"], self._compiled["audit"]
            self._max_cards, self._actors = p.max_cards, []
        elif kind == "archived_v1":
            # Local import keeps the current record tool independent of the old
            # selection/composition/provider contracts.
            from .stamp_materials import StampPolicy, build_stamps

            materials = build_stamps(source, StampPolicy(**(policy or {})))
            self._policy = materials["policy"]
            self._frames = [s["snapshot"] for s in materials["stamps"]]
            self._audit = {k: p["audit"] for k, p in materials["pools"].items()}
            self._max_cards, self._actors = materials["max_cards"], materials["actors"]
        else:
            raise ValueError("unsupported stamp source")
        self._by_id = {f["id"]: f for f in self._frames}
        if len(self._by_id) != len(self._frames):
            raise ValueError("duplicate stamp ID")
        self._materials = {f["id"]: self._project(f) for f in self._frames}
        self._versions = {
            f["id"]: payload_hash({"source": self.source_version, "policy": self._policy,
                                   "frame": f, "material": self._materials[f["id"]]})
            for f in self._frames
        }

    @property
    def source_version(self):
        return self._source_version

    @property
    def refs(self):
        return tuple(StampRef(id=f["id"], version=self._versions[f["id"]]) for f in self._frames)

    @property
    def max_cards(self):
        return self._max_cards

    @property
    def actors(self):
        return deepcopy(self._actors)

    def resolve(self, ref: StampRef):
        ref = StampRef.model_validate(ref)
        if self._versions.get(ref.id) != ref.version:
            raise ValueError("unknown or stale stamp reference")
        return deepcopy(self._by_id[ref.id])

    def anchor(self, ref: StampRef):
        frame = self.resolve(ref)
        if self._kind in {"record_how", "action_background", "action_background_v2"}:
            return deepcopy(self._compiled["anchors"][frame["id"]])
        if self._kind == "archived_v1":
            return {**frame["anchor"], "chain": frame["chain"], "location": None}
        record = self._records[frame["id"]]
        return {
            "record_ref": record.ref.model_dump(mode="json"),
            "session_id": record.session_id,
            "event_at": record.event_at.isoformat(), "time_basis": record.time_basis,
            "location": record.location.model_dump(mode="json") if record.location else None,
        }

    def project(self, ref: StampRef):
        frame = self.resolve(ref)
        return deepcopy(self._materials[frame["id"]])

    def _project(self, frame):
        if self._kind in {"record_how", "action_background", "action_background_v2"}:
            return deepcopy(self._compiled["projections"][frame["id"]])
        if self._kind == "archived_v1":
            from .stamp_materials import compact_stamp

            return compact_stamp({"snapshot": frame})
        record = self._records[frame["id"]]
        result = {
            "id": frame["id"], "tag": "user_record",
            "record": record.content.model_dump(mode="json"),
            "when": {"event_at": record.event_at.isoformat(), "basis": record.time_basis},
            "context": [], "relations": [],
        }
        for eid in frame["context_envelope_ids"]:
            envelope = self._envelopes[eid]
            is_current = envelope.target.record == record.ref
            result["context"].append({
                **_project_envelope(envelope),
                "applies_to": envelope.target.record.model_dump(mode="json"),
                "relation_to_stamp": "same_record" if is_current else "prior_record_query",
                "elapsed_s": (record.event_at - envelope.target.event_at).total_seconds(),
            })
        if frame["previous_action_id"] and record.time_basis != "session_fallback":
            prior = self._records[frame["previous_action_id"]]
            result["relations"].append({
                "type": "after_action_record", "from_id": _record_id(prior), "to_id": frame["id"],
                "action": prior.content.model_dump(mode="json"),
                "elapsed_s": (record.event_at - prior.event_at).total_seconds(),
                "basis": "record_timestamp_difference", "continuous_presence": "not_established",
            })
        return result

    def query(self):
        return [{"ref": ref.model_dump(mode="json"), "required": self.resolve(ref)["required"],
                 "material": self.project(ref)} for ref in self.refs]

    def dump(self):
        book = {
            "schema_version": "stamp-book-v1", "source_kind": self._kind,
            "source": json.loads(self._source), "source_version": self.source_version,
            "policy": deepcopy(self._policy),
            "stamps": [{"ref": r.model_dump(mode="json"), "frame": self.resolve(r)}
                       for r in self.refs],
            "slot_audit": deepcopy(self._audit),
        }
        if self._kind in {"record_how", "action_background"}:
            book["how_catalog"] = deepcopy(self._compiled["catalog"])
        if self._kind == "action_background":
            book["derived_action_catalog"] = deepcopy(self._compiled["derived_action_catalog"])
        if self._kind == "action_background_v2":
            book["scene_plan"] = deepcopy(self._compiled["plan"])
        return book

    @classmethod
    def load(cls, value):
        tool = cls(value["source_kind"], value["source"], value["policy"])
        if tool.dump() != value:
            raise ValueError("stamp book changed or failed deterministic replay")
        return tool
