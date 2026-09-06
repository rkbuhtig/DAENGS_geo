"""Observed exports -> existing geo calculations -> diary pieces. No simulator truth input."""

import math
from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from app.features.territory.dwell import metres_between, read_at
from app.features.territory.layers import Aggregation, LayerSpec, Projection, Selector, select
from app.features.territory.paint import NARROW_STEP, paint_sheet, paint_spec
from app.features.walk.curve import compute_curve
from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkFix, WalkSession
from app.features.walk.observation import (
    CANDIDATE_MIN_S,
    CANDIDATE_SPEED_MPS,
    MICRO_OBSERVATION_VERSION,
    extract_observations,
)

from .cached_environment import project_snapshots
from .contracts import Contract, Evidence, Piece
from .storage import digest


class QueryPolicy(Contract):
    version: str
    since: datetime
    timezone: str
    radius_m: float = Field(gt=0)
    radius_u: float = Field(gt=0)
    min_peak: float = Field(ge=0)
    tags: dict[str, str]
    empty_sheets: str
    target_sources: list[str]
    environment_match_m: float = Field(gt=0)

    @model_validator(mode="after")
    def valid_policy(self):
        ZoneInfo(self.timezone)
        if self.since.tzinfo is None:
            raise ValueError("history query requires timezone")
        if self.empty_sheets not in ("include", "exclude"):
            raise ValueError("empty_sheets must be include or exclude")
        if not self.target_sources or not set(self.target_sources) <= {
            "micro_slow",
            "behavior_pins",
            "session_endpoints",
        }:
            raise ValueError("unsupported spatial query target source")
        return self


def measure(export):
    if set(export) != {"format", "session", "fixes"} or export["format"] != 1:
        raise ValueError("adapter requires an observed walk export, not a simulator bundle")
    session = WalkSession.model_validate(export["session"])
    if session.ended_at is None or session.ended_at <= session.started_at:
        raise ValueError("a completed positive-duration session is required")
    fixes = [WalkFix.model_validate(f) for f in export["fixes"]]
    if len({f.client_seq for f in fixes}) != len(fixes):
        raise ValueError("duplicate observation sequence IDs")
    fixes.sort(key=lambda f: f.client_seq)
    if any(not session.started_at <= f.at <= session.ended_at for f in fixes):
        raise ValueError("observation outside session")
    return compute_facts(session.id, session.dog_id, session.started_at, session.ended_at, fixes)


def timeline(computed):
    groups = []
    for segment in computed.trail.segments:
        if (
            not groups
            or groups[-1][-1].b.client_seq != segment.a.client_seq
            or groups[-1][-1].chain_index != segment.chain_index
            or groups[-1][-1].moving != segment.moving
        ):
            groups.append([])
        groups[-1].append(segment)
    return [
        {
            "id": f"route-{i:03d}",
            "started_at": group[0].a.at.isoformat(),
            "ended_at": group[-1].b.at.isoformat(),
            "chain_index": group[0].chain_index,
            "moving_classification": group[0].moving,
            "duration_s": math.fsum(s.dt for s in group),
            "observed_path_m": math.fsum(s.dist for s in group),
            "mean_observed_speed_mps": math.fsum(s.dist for s in group)
            / math.fsum(s.dt for s in group),
            "from": {"lat": group[0].a.lat, "lng": group[0].a.lng},
            "to": {"lat": group[-1].b.lat, "lng": group[-1].b.lng},
            "first_client_seq": group[0].a.client_seq,
            "last_client_seq": group[-1].b.client_seq,
        }
        for i, group in enumerate(groups, 1)
    ]


def passages(computed, centre, radius_m):
    """Consecutive accepted fixes within a query circle; not exact boundary crossing times."""
    edges = {(s.a.client_seq, s.b.client_seq) for s in computed.trail.segments}
    points = {f.client_seq: f for s in computed.trail.segments for f in (s.a, s.b)}
    groups, current = [], []
    for fix in sorted(points.values(), key=lambda f: f.client_seq):
        inside = metres_between((fix.lat, fix.lng), centre) <= radius_m
        if current and (not inside or (current[-1].client_seq, fix.client_seq) not in edges):
            groups.append(current)
            current = []
        if inside:
            current.append(fix)
    if current:
        groups.append(current)
    return [
        {
            "first_observed_at": g[0].at.isoformat(),
            "last_observed_at": g[-1].at.isoformat(),
            "first_client_seq": g[0].client_seq,
            "last_client_seq": g[-1].client_seq,
            "fix_count": len(g),
        }
        for g in groups
    ]


def build_evidence(current_export, history_exports, pins, policy: QueryPolicy, snapshots):
    computed = measure(current_export)
    facts = computed.facts
    if policy.since >= facts.started_at:
        raise ValueError("history period must start before current session")
    pieces, anchors = [], []
    source_hash = digest(current_export)
    origin = facts.evidence_origin

    def add(identifier, kind, value, meaning, links=None, provenance=None, status=None):
        pieces.append(
            Piece(
                id=identifier,
                kind=kind,
                session_links=links or {},
                value=value,
                meaning=meaning,
                provenance={
                    "observation_sha256": source_hash,
                    "calculation_version": facts.calculation_version,
                    **(provenance or {}),
                },
                measurement_status=status or f"computed_from_{origin}_observations",
            )
        )

    add(
        "session-facts",
        "session_macro",
        facts.model_dump(mode="json"),
        "geo compute_facts의 결과. avg_speed_mps는 이동으로 분류된 거리/시간이다. "
        "정지 판정은 행동핀과 다르다.",
    )
    route = timeline(computed)
    for row in route:
        add(
            row["id"],
            "route_interval",
            row,
            "동일 moving 분류와 연속성을 갖는 canonical 구간을 묶은 시간축. 최종 장면이 아니다.",
            {"started_at": row["started_at"], "ended_at": row["ended_at"]},
        )
    add(
        "session-curve",
        "session_macro",
        {
            "buckets": [
                b.to_dict()
                for b in compute_curve(facts.started_at, facts.ended_at, computed.trail.segments)
            ]
        },
        "geo compute_curve의 세션 시간 10등분. still_s는 정지 이벤트 시간과 다른 관측 분류다.",
    )
    add(
        "measurement-quality",
        "measurement",
        {
            "quality": computed.trail.quality.to_dict(),
            "canonical_segment_s": math.fsum(s.dt for s in computed.trail.segments),
            "gap_elapsed_s": math.fsum(g.dt for g in computed.trail.gaps),
            "micro_observation_version": MICRO_OBSERVATION_VERSION,
            "micro_candidate_speed_mps": CANDIDATE_SPEED_MPS,
            "micro_candidate_min_s": CANDIDATE_MIN_S,
        },
        "기존 geo 계산기의 측정 상태와 저속 후보 추출 범위. 감정·행동 동기를 측정하지 않는다.",
    )
    observations = extract_observations(
        facts.session_id, computed.trail.segments, computed.trail.gaps
    )
    for observation in observations:
        row = observation.to_row()
        for key in ("started_at", "ended_at"):
            row[key] = row[key].isoformat()
        identifier = f"micro-{observation.index:03d}"
        add(
            identifier,
            "micro",
            row,
            "geo 저속·관측 공백 후보. path_m은 지터 포함 경로 길이, "
            "net_m은 양끝 변위, span_m은 관측 중심에서 가장 먼 점까지의 거리다.",
            {"started_at": row["started_at"], "ended_at": row["ended_at"]},
        )
        if observation.kind == "slow" and "micro_slow" in policy.target_sources:
            anchors.append({"id": identifier, "lat": observation.lat, "lng": observation.lng})
    for pin in pins:
        at = datetime.fromisoformat(pin["at"])
        if not facts.started_at <= at <= facts.ended_at:
            raise ValueError("behavior pin outside current session")
        add(
            pin["id"],
            "behavior_pin",
            pin,
            "별도로 작성한 합성 보호자 관찰 기록과 메모.",
            {"at": pin["at"], "lat": pin["lat"], "lng": pin["lng"]},
            {"pin_input_sha256": digest(pins)},
            "synthetic_pin",
        )
        if "behavior_pins" in policy.target_sources:
            anchors.append({"id": pin["id"], "lat": pin["lat"], "lng": pin["lng"]})
    if computed.trail.segments and "session_endpoints" in policy.target_sources:
        for label, fix in (
            ("start", computed.trail.segments[0].a),
            ("end", computed.trail.segments[-1].b),
        ):
            identifier = f"session-{label}"
            add(
                identifier,
                "route_endpoint",
                fix.model_dump(mode="json"),
                "수용된 경로의 처음/마지막 관측점. 주거지 여부는 입력하지 않았다.",
            )
            anchors.append({"id": identifier, "lat": fix.lat, "lng": fix.lng})

    spec = LayerSpec(
        Selector.of(**policy.tags),
        Aggregation("occupancy", policy.min_peak),
        Projection.from_paint_spec(paint_spec(policy.radius_u, NARROW_STEP)),
    )
    sheets, receipts, excluded, seen = [], [], [], set()
    for export in history_exports:
        session = WalkSession.model_validate(export["session"])
        if session.id in seen or session.id == facts.session_id:
            raise ValueError("duplicate or current session in history corpus")
        seen.add(session.id)
        if (
            session.dog_id != facts.dog_id
            or session.ended_at is None
            or session.ended_at >= facts.started_at
            or not policy.since <= session.started_at < facts.started_at
        ):
            excluded.append({"session_id": session.id, "reason": "pet_or_period"})
            continue
        measured = measure(export)
        sheet = paint_sheet(
            session.id,
            session.started_at.astimezone(ZoneInfo(policy.timezone)),
            measured.trail.segments,
            policy.radius_u,
            NARROW_STEP,
        )
        if not sheet.occupancy and policy.empty_sheets == "exclude":
            excluded.append({"session_id": session.id, "reason": "empty_sheet"})
            continue
        sheets.append(sheet)
        receipts.append(
            {
                "session_id": session.id,
                "observation_sha256": digest(export),
                "canonical_segment_s": math.fsum(s.dt for s in measured.trail.segments),
                "occupancy_mass_s": math.fsum(sheet.occupancy.values()),
                "paint_fp": sheet.paint_fp,
                "cells": [
                    {"q": q, "r": r, "occupancy_s": mass, "peak": sheet.peak[(q, r)]}
                    for (q, r), mass in sorted(sheet.occupancy.items())
                ],
            }
        )
    chosen = select(sheets, spec)
    selected_ids = [s.walk_id for s in chosen]
    spatial_audit = []
    for anchor in anchors:
        centre = (anchor["lat"], anchor["lng"])
        result = read_at(sheets, spec, centre, policy.radius_m)
        contributions = []
        for sheet in chosen:
            one = read_at([sheet], spec, centre, policy.radius_m)
            contributions.append(
                {"session_id": sheet.walk_id, "mass_s": one.mass, "appeared": one.walks == 1}
            )
        value = {
            "centre": {"lat": centre[0], "lng": centre[1]},
            "radius_m": policy.radius_m,
            "appeared_walks": result.walks,
            "selected_walks": result.selected,
            "appearance_ratio": result.visit_rate,
            "occupancy_mass_s": result.mass,
            "mass_per_appeared_walk_s": result.dwell_per_visit,
            "mass_per_selected_walk_s": result.expected_dwell_per_walk,
            "current_observed_passages": passages(computed, centre, policy.radius_m),
        }
        provenance = {
            "query_policy": policy.model_dump(mode="json"),
            "until_exclusive": facts.started_at.isoformat(),
            "dog_id": facts.dog_id,
            "selected_session_ids": selected_ids,
            "history_observation_sha256": digest(history_exports),
            "layer_spec_fingerprint": result.spec_fingerprint,
            "paint_spec": asdict(spec.projection.paint_spec),
            "contributions_sha256": digest(contributions),
            "calculator": "territory.dwell.read_at",
        }
        add(
            "spatial-" + anchor["id"],
            "past_spatial_tendency",
            value,
            "선택한 과거 산책의 셀로판에서 반경 안 셀 중심의 양수 시간 질량을 집계했다. "
            "산책 하나는 공간 등장에 최대 1회 기여한다. 질량은 공간에 배분한 관측 초이며 "
            "실제 정지 시간·시설 방문 횟수·과거 행동 횟수가 아니다. current_observed_passages는 "
            "이번 관측점의 반경 내 연속 출현이며 정확한 경계 통과 시각은 아니다.",
            {"anchor_id": anchor["id"]},
            provenance,
            "computed_from_synthetic_history" if origin == "mock" else "computed_history",
        )
        spatial_audit.append(
            {"piece_id": "spatial-" + anchor["id"], "value": value, "contributions": contributions}
        )
    pieces.extend(project_snapshots(snapshots, anchors, policy.environment_match_m))
    evidence = Evidence(
        session_id=facts.session_id,
        started_at=facts.started_at.astimezone(ZoneInfo(policy.timezone)),
        ended_at=facts.ended_at.astimezone(ZoneInfo(policy.timezone)),
        context={
            "pet": "두부（실험용）",
            "observation_origin": origin,
            "display_timezone": policy.timezone,
            "scope": "현재·과거 GPS와 행동핀은 합성. 환경은 저장된 실제 지도 응답. "
            "도로망 검증·실제 보호자 경험·당시 날씨는 제공하지 않는다.",
        },
        pieces=pieces,
    )
    audit = {
        "source_observation_sha256": source_hash,
        "history_receipts": receipts,
        "excluded_history": excluded,
        "selected_session_ids": selected_ids,
        "query_anchors": anchors,
        "spatial_readings": spatial_audit,
        "timeline": route,
        "evidence_sha256": digest(evidence.model_dump(mode="json")),
    }
    return evidence, audit
