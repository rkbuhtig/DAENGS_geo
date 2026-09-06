"""Loss-preserving adapter for the earlier synthetic experiment, not a geo query engine."""

from .contracts import Evidence, Piece


def from_scenario(source: dict) -> Evidence:
    if source.get("schema_version") == "diary-evidence-v1":
        return Evidence.model_validate(source)
    session = source["session"]
    pieces = []

    def add(item, kind, meaning, provenance=None):
        pieces.append(
            Piece(
                id=item["id"],
                kind=kind,
                session_links={
                    k: item[k] for k in ("from", "to", "at", "location", "scope") if k in item
                },
                value=item,
                meaning=meaning,
                provenance={"adapter": "four-inputs-fixture-v1", **(provenance or {})},
                measurement_status="synthetic_fixture",
            )
        )

    for item in source["micro_observations"]:
        add(item, "micro", "이번 세션 구간의 관측량. 단위와 필드 의미는 value 원문을 따른다.")
    for item in source["environment"]:
        add(item, "environment", "해당 위치·시점의 환경 자료와 미확인 사항.")
    macro = source["macro_spatial_tendencies"]
    for item in macro["pieces"]:
        add(item, "past_spatial_tendency", macro["coverage_note"], macro["policy_receipt"])
    for item in source["behavior_pins"]:
        add(item, "behavior_pin", source["recording_note"])
    add(
        {"id": "session-route", "session": session},
        "session_macro",
        "이번 산책의 전체 시간·위치·이동 순서.",
    )
    add(
        {"id": "measurement-context", **source["measurement_context"]},
        "measurement",
        "이번 산책의 관측 품질과 측정하지 않은 내용.",
    )
    add(
        {"id": "recording-note", "text": source["recording_note"]},
        "recording_context",
        "행동 기록의 수집 맥락.",
    )
    return Evidence(
        session_id=session["id"],
        started_at=session["started_at"],
        ended_at=session["ended_at"],
        pieces=pieces,
        context={"fixture_note": source["fixture_note"], "session": session},
    )
