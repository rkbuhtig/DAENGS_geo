"""Import only the saved V3 input; model output/reviews never become source evidence."""

from datetime import datetime, timedelta

from .candidates import CATALOG_KEY, Candidate, CandidateCatalog, Gap, catalog_for
from .contracts import Evidence, Piece
from .storage import digest


def from_selection_case(
    case: dict, *, started_at: datetime, session_id: str, composition_mode: str = "individual"
) -> Evidence:
    packet = case["input"]
    if packet.get("format") != "scene-purpose-v3" or packet.get("synthetic_walk") is not True:
        raise ValueError("adapter accepts only archived synthetic scene-purpose-v3 inputs")
    fingerprint = digest(packet)
    if fingerprint != case["input_sha256"]:
        raise ValueError("archived input hash mismatch")
    if started_at.tzinfo is None or not session_id:
        raise ValueError("explicit session ID and timezone-aware synthetic start are required")
    if packet["session"]["start_s"] != 0:
        raise ValueError("archived session must start at offset zero")

    def at(seconds):
        return started_at + timedelta(seconds=seconds)

    pieces = []
    for actor in packet["actors"]:
        pieces.append(Piece(
            id=actor["id"], kind="who", session_links={}, value=actor,
            meaning=actor["text"], provenance={"source_input_sha256": fingerprint},
            measurement_status="synthetic_actor",
        ))
    candidates = []
    for event in packet["events"]:
        start, end = at(event["start_s"]), at(event["end_s"])
        atoms = event.get("evidence", [])
        for atom in atoms:
            pieces.append(Piece(
                id=atom["id"], kind=atom["kind"],
                session_links={"candidate_id": event["id"], "chain": event["chain"],
                               "from": start.isoformat(), "to": end.isoformat()},
                value=atom, meaning=atom["text"],
                provenance={"source_input_sha256": fingerprint, "source_event_id": event["id"],
                            "kind": "archived_derived_evidence",
                            "note": "Public spatial cache with synthetic route/pins; not recomputed"},
                measurement_status="archived_synthetic_experiment",
            ))
        candidates.append(Candidate(
            id=event["id"], role=event["role"], time_kind="point" if start == end else "interval",
            start_at=start, end_at=end, chain=event["chain"],
            card_eligible=event["card_eligible"], required=event.get("required", False),
            why_keep=event["why_keep"], evidence_ids=[a["id"] for a in atoms],
            subject_ids=event.get("who_ids", []),
            primary_evidence_id=event.get("primary_evidence_id"),
            source_event_id=event["id"], source_input_sha256=fingerprint,
        ))
    catalog = CandidateCatalog(
        policy_id="scene-purpose-v3-archived", source_revision=fingerprint,
        max_scenes=packet["limits"]["scene_count_max"], candidates=candidates,
        composition_mode=composition_mode,
        gaps=[Gap(start_at=at(g["start_s"]), end_at=at(g["start_s"] + g["duration_s"]))
              for g in packet["gaps"]],
    )
    evidence = Evidence(
        session_id=session_id, started_at=started_at, ended_at=at(packet["session"]["end_s"]),
        context={
            CATALOG_KEY: catalog.model_dump(mode="json"), "synthetic_walk": True,
            "source_input_sha256": fingerprint, "synthetic_started_at": True,
            "adapter_version": "scene-purpose-to-evidence-v1",
            "location_note": "Archive contains event IDs, not observation coordinates; unresolved",
        }, pieces=pieces,
    )
    catalog_for(evidence)
    return evidence
