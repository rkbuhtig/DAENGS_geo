"""Step 1: record references and appendable context envelopes, with no I/O or LLM.

This is an experimental snapshot contract, not an App/Dev write API. Existing
records keep their storage and identity. Cross-object checks live in Snapshot.
"""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RecordRef(Contract):
    store: Literal["walk_entry", "walk_photo"]
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    version_kind: Literal["revision", "sha256"]

    @property
    def key(self) -> tuple[str, str]:
        return self.store, self.id

    @model_validator(mode="after")
    def digest_format(self):
        if self.version_kind == "sha256" and (
            len(self.version) != 64 or any(c not in "0123456789abcdef" for c in self.version)
        ):
            raise ValueError("source sha256 must be a lowercase hex digest")
        return self


class Point(Contract):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class Location(Contract):
    point: Point
    captured_at: AwareDatetime
    accuracy_m: float | None = Field(default=None, ge=0)
    basis: Literal["device_fix", "route_observation"]
    observation_ref: str = Field(min_length=1)


class Behavior(Contract):
    kind: Literal["behavior"]
    code: Literal["sniffing", "excretion", "barking"]
    pet_id: str | None = None


class Note(Contract):
    kind: Literal["note"]
    text: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def nonblank(self):
        if not self.text.strip():
            raise ValueError("note cannot be blank; do not rewrite the original text")
        return self


class Photo(Contract):
    kind: Literal["photo"]
    media_ref: str = Field(min_length=1)


class Record(Contract):
    ref: RecordRef
    owner_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    session_pet_ids: tuple[str, ...]
    event_at: AwareDatetime
    time_basis: Literal["recorded_at", "photo_capture", "route_observation", "session_fallback"]
    authored_at: AwareDatetime | None
    location: Location | None
    content: Annotated[Behavior | Note | Photo, Field(discriminator="kind")]

    @model_validator(mode="after")
    def source_and_anchors(self):
        photo = isinstance(self.content, Photo)
        if (self.ref.store == "walk_photo") != photo:
            raise ValueError("record kind disagrees with its original store")
        if not isinstance(self.content, Note) and self.location is None:
            raise ValueError("behavior and captured photo require an observed location")
        if photo != (self.time_basis == "photo_capture"):
            raise ValueError("photo records retain capture time")
        if self.time_basis == "route_observation" and (
            self.location is None or self.location.basis != "route_observation"
            or self.event_at != self.location.captured_at
        ):
            raise ValueError("backfilled record must use the chosen route observation time")
        if (self.location and self.location.basis == "route_observation"
                and self.time_basis != "route_observation"):
            raise ValueError("route attachment must be explicit")
        if self.time_basis == "session_fallback" and (
            not isinstance(self.content, Note) or self.location is not None
        ):
            raise ValueError("session fallback cannot locate an event")
        if len(self.session_pet_ids) != len(set(self.session_pet_ids)):
            raise ValueError("duplicate session pet")
        if (isinstance(self.content, Behavior) and self.content.pet_id is not None
                and self.content.pet_id not in self.session_pet_ids):
            raise ValueError("behavior subject must belong to the session")
        return self


class TimeRange(Contract):
    start_at: AwareDatetime
    end_at: AwareDatetime

    @model_validator(mode="after")
    def ordered(self):
        if self.end_at < self.start_at:
            raise ValueError("reversed time support")
        return self


class Target(Contract):
    record: RecordRef
    event_at: AwareDatetime
    point: Point | None
    radius_m: float | None = Field(default=None, gt=0)


Tag = Literal[
    "space.park", "space.river", "space.facility", "environment.weather", "movement.window",
]


class Provenance(Contract):
    provider: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    retrieved_at: AwareDatetime | None
    temporal_basis: Literal["event_observation", "lookup_snapshot", "unknown"]
    valid_time: TimeRange | None
    policy_version: str = Field(min_length=1)
    synthetic: bool


def payload_hash(payload: dict[str, JsonValue]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Envelope(Contract):
    id: str = Field(min_length=1)
    target: Target
    tags: tuple[Tag, ...] = Field(min_length=1)
    status: Literal["known", "partial", "empty", "unavailable", "not_requested"]
    reason: str | None
    provenance: Provenance
    payload_format: str = Field(min_length=1)
    payload: dict[str, JsonValue] | None
    payload_sha256: str | None
    supersedes: str | None = None

    @model_validator(mode="after")
    def integrity(self):
        if len(self.tags) != len(set(self.tags)):
            raise ValueError("duplicate envelope tags")
        has_result = self.status in {"known", "partial", "empty"}
        if has_result:
            if self.payload is None or self.provenance.retrieved_at is None:
                raise ValueError("result requires payload and retrieval time")
            if self.payload_sha256 != payload_hash(self.payload):
                raise ValueError("payload hash mismatch")
        elif self.payload is not None or self.payload_sha256 is not None:
            raise ValueError("missing result cannot contain successful data")
        if self.status in {"partial", "unavailable", "not_requested"} and not self.reason:
            raise ValueError("incomplete or absent result requires a reason")
        if self.status == "not_requested" and self.provenance.retrieved_at is not None:
            raise ValueError("not-requested envelope has no retrieval time")
        if self.target.point is None and (self.status != "not_requested"
                                          or self.target.radius_m is not None):
            raise ValueError("these collectors cannot query an unlocated record")
        if self.provenance.temporal_basis == "event_observation":
            span = self.provenance.valid_time
            if span is None or not span.start_at <= self.target.event_at <= span.end_at:
                raise ValueError("event observation must cover the record time")
        return self


class RecordEnvelopeSnapshot(Contract):
    schema_version: Literal["walk-record-envelopes-v1"]
    synthetic: bool
    owner_id: str = Field(min_length=1)
    records: tuple[Record, ...]
    envelopes: tuple[Envelope, ...]
    # Explicit consumption manifest: append history alone never selects a payload for the LLM/UI.
    selected_envelope_ids: tuple[str, ...]

    @model_validator(mode="after")
    def references(self):
        records = {r.ref.key: r for r in self.records}
        if len(records) != len(self.records):
            raise ValueError("snapshot needs one version per original record")
        if any(r.owner_id != self.owner_id for r in self.records):
            raise ValueError("snapshot crosses owner scope")
        envelopes = {}
        for envelope in self.envelopes:
            if envelope.id in envelopes:
                raise ValueError("duplicate envelope ID")
            record = records.get(envelope.target.record.key)
            if record is None or record.ref != envelope.target.record:
                raise ValueError("unknown or stale record reference")
            point = record.location.point if record.location else None
            if envelope.target.event_at != record.event_at or envelope.target.point != point:
                raise ValueError("envelope silently changes record time or location")
            if envelope.provenance.synthetic != self.synthetic:
                raise ValueError("synthetic evidence must not masquerade as real data")
            if envelope.supersedes is not None:
                previous = envelopes.get(envelope.supersedes)
                if previous is None or (previous.target != envelope.target
                                        or set(previous.tags) != set(envelope.tags)
                                        or previous.provenance.provider != envelope.provenance.provider
                                        or previous.provenance.operation != envelope.provenance.operation):
                    raise ValueError("replacement needs a prior envelope of the same query scope")
            envelopes[envelope.id] = envelope
        selected = set(self.selected_envelope_ids)
        if len(selected) != len(self.selected_envelope_ids) or not selected <= envelopes.keys():
            raise ValueError("duplicate or missing selected envelope")
        scopes = set()
        for id_ in self.selected_envelope_ids:
            envelope = envelopes[id_]
            target = envelope.target
            # Aware datetimes compare by instant, including different UTC offset spellings.
            scope = (target.record.key, target.record.version_kind, target.record.version,
                     target.event_at, (target.point.lat, target.point.lng) if target.point else None,
                     target.radius_m, tuple(sorted(envelope.tags)),
                     envelope.provenance.provider, envelope.provenance.operation)
            if scope in scopes:
                raise ValueError("multiple results selected for the same query scope")
            scopes.add(scope)
        return self


def main():
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, nargs="?", default=(
        Path(__file__).parent / "fixtures" / "record_envelopes.json"
    ))
    parser.add_argument("--schema", action="store_true", help="Print JSON Schema; no validation")
    args = parser.parse_args()
    if args.schema:
        print(json.dumps(RecordEnvelopeSnapshot.model_json_schema(), ensure_ascii=False, indent=2))
        return
    snapshot = RecordEnvelopeSnapshot.model_validate_json(args.path.read_text(encoding="utf-8"))
    print(json.dumps({"schema_version": snapshot.schema_version, "synthetic": snapshot.synthetic,
                      "records": len(snapshot.records), "envelopes": len(snapshot.envelopes),
                      "selected_envelopes": len(snapshot.selected_envelope_ids),
                      "located_records": sum(r.location is not None for r in snapshot.records)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
