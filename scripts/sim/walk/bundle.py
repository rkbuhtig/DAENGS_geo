"""시나리오의 원인·실제 동선·관측·파생 결과를 함께 남긴다."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.features.territory.geojson import dumps_cellophane_geojson
from app.features.territory.paint import NARROW_STEP, paint_sheet
from app.features.walk.curve import compute_curve
from app.features.walk.facts import ComputedFacts, compute_facts
from app.features.walk.observation import extract_observations, moving_speed_profile
from scripts.sim.walk.kinematics import MotionTruth, integrate_motion
from scripts.sim.walk.model import GENERATOR_VERSION, BehaviorName, behavior_preset
from scripts.sim.walk.route import RouteName, route_preset
from scripts.sim.walk.sensor import ObservedWalk, PerfectSensor, observe_perfectly

DEFAULT_START = datetime(2026, 1, 1, tzinfo=UTC)
DEFAULT_ORIGIN = (37.4979, 127.0276)


@dataclass(frozen=True)
class ScenarioArtifacts:
    manifest: dict[str, object]
    truth: dict[str, object]
    observed: ObservedWalk
    computed: ComputedFacts
    derived: dict[str, object]
    cellophane_geojson: str


def _scenario_session_id(
    *,
    behavior_name: BehaviorName,
    route_name: RouteName,
    length_m: float,
    seed: int,
    sample_interval_s: float,
    chain_breaks_m: tuple[float, ...],
    dog_id: str,
    started_at: datetime,
    origin_lat: float,
    origin_lng: float,
) -> str:
    """관측 결과를 바꾸는 모든 입력으로 재현 가능한 실행 ID를 만든다."""
    signature = {
        "generator_version": GENERATOR_VERSION,
        "behavior": behavior_name,
        "route": route_name,
        "length_m": length_m,
        "seed": seed,
        "sample_interval_s": sample_interval_s,
        "chain_breaks_m": chain_breaks_m,
        "dog_id": dog_id,
        "started_at": started_at.isoformat(),
        "origin_lat": origin_lat,
        "origin_lng": origin_lng,
    }
    encoded = json.dumps(
        signature, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:16]
    return f"sim-v{GENERATOR_VERSION}-{behavior_name}-{route_name}-{digest}"


def _derived_payload(computed: ComputedFacts, truth: MotionTruth) -> dict[str, object]:
    profile = moving_speed_profile(computed.segments)
    curve = compute_curve(
        computed.facts.started_at, computed.facts.ended_at, computed.segments
    )
    observations = extract_observations(
        computed.facts.session_id, computed.segments, computed.gaps
    )
    observation_rows = []
    for observation in observations:
        row = observation.to_row()
        row["started_at"] = row["started_at"].isoformat()
        row["ended_at"] = row["ended_at"].isoformat()
        observation_rows.append(row)
    return {
        "facts": computed.facts.model_dump(mode="json"),
        "quality": computed.quality.to_dict(),
        "events": [event.model_dump(mode="json") for event in computed.events],
        "curve": [bucket.to_dict() for bucket in curve],
        "moving_speed_profile": profile.to_dict() if profile else None,
        "observations": observation_rows,
        "segments": [
            {
                "from_client_seq": segment.a.client_seq,
                "to_client_seq": segment.b.client_seq,
                "chain_index": segment.chain_index,
                "duration_s": round(segment.dt, 6),
                "distance_m": round(segment.dist, 6),
                "speed_mps": round(segment.dist / segment.dt, 6),
                "moving": segment.moving,
            }
            for segment in computed.segments
        ],
        "truth_duration_s": round(truth.duration_s, 6),
        "accepted_segment_s": round(math.fsum(segment.dt for segment in computed.segments), 6),
    }


def build_scenario(
    *,
    behavior_name: BehaviorName = "exploratory",
    route_name: RouteName = "s-curve",
    length_m: float = 600.0,
    seed: int = 48123,
    sample_interval_s: float = 5.0,
    chain_breaks_m: tuple[float, ...] = (),
    session_id: str | None = None,
    dog_id: str = "simulated-dog",
    started_at: datetime = DEFAULT_START,
    origin_lat: float = DEFAULT_ORIGIN[0],
    origin_lng: float = DEFAULT_ORIGIN[1],
) -> ScenarioArtifacts:
    if session_id is not None and not 1 <= len(session_id) <= 128:
        raise ValueError("session_id must contain 1 to 128 characters")
    resolved_session_id = session_id or _scenario_session_id(
        behavior_name=behavior_name,
        route_name=route_name,
        length_m=length_m,
        seed=seed,
        sample_interval_s=sample_interval_s,
        chain_breaks_m=chain_breaks_m,
        dog_id=dog_id,
        started_at=started_at,
        origin_lat=origin_lat,
        origin_lng=origin_lng,
    )
    behavior = behavior_preset(behavior_name, length_m, seed)
    route = route_preset(route_name, length_m)
    motion = integrate_motion(behavior, route)
    sensor = PerfectSensor(
        sample_interval_s=sample_interval_s,
        accuracy_m=3.0,
        chain_breaks_m=chain_breaks_m,
    )
    observed = observe_perfectly(
        motion,
        sensor,
        session_id=resolved_session_id,
        dog_id=dog_id,
        started_at=started_at,
        origin_lat=origin_lat,
        origin_lng=origin_lng,
    )
    computed = compute_facts(
        resolved_session_id,
        dog_id,
        started_at,
        observed.ended_at,
        list(observed.fixes),
    )
    sheet = paint_sheet(
        resolved_session_id, started_at, computed.segments, 8.0, NARROW_STEP
    )
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "session_id": resolved_session_id,
        "behavior": behavior.to_dict(),
        "route": route.to_dict(),
        "sensor": sensor.to_dict(),
        "origin": {"lat": origin_lat, "lng": origin_lng},
        "truth_semantics": {
            "latent_state": "generator input, not a product judgment",
            "target_speed_mps": "continuous behavior speed field v(s)",
            "forward_speed_mps": "integrated progress change per second",
            "ground_speed_mps": "physical 2D speed before GPS",
            "cellophane_occupancy": "derived by canonical Paint, never generated directly",
        },
    }
    truth_payload = {
        "duration_s": round(motion.duration_s, 6),
        "sample_interval_s": 1.0,
        "samples": [sample.to_dict() for sample in motion.samples(1.0)],
    }
    return ScenarioArtifacts(
        manifest=manifest,
        truth=truth_payload,
        observed=observed,
        computed=computed,
        derived=_derived_payload(computed, motion),
        cellophane_geojson=dumps_cellophane_geojson(sheet, computed.segments),
    )


def write_scenario(out: Path, artifacts: ScenarioArtifacts) -> None:
    """기존 실행 결과를 덮지 않는다. 비어 있거나 아직 없는 폴더만 받는다."""
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"output directory is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)
    payloads = {
        "manifest.json": artifacts.manifest,
        "truth.json": artifacts.truth,
        "walk-export.json": artifacts.observed.to_export(),
        "derived.json": artifacts.derived,
    }
    for filename, payload in payloads.items():
        (out / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    (out / "cellophane.geojson").write_text(
        artifacts.cellophane_geojson + "\n", encoding="utf-8"
    )
