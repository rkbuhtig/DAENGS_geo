"""Rule-based HOW material extraction from a canonical walk, before pool selection.

Local stay, straight runs, visible turns and adjacent-leg retracing describe the
recording device's geometry. No place lookup, inferred purpose, LLM or stamp edit.
Thresholds are explicit exploratory policy, not calibrated walking classifiers.
"""

import math
import statistics
from dataclasses import dataclass
from datetime import UTC
from itertools import pairwise
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from app.features.walk.facts import CanonicalTrail, compute_facts
from app.features.walk.models import WalkFix

from .record_envelopes import Contract, payload_hash


class HowSource(Contract):
    schema_version: Literal["how-source-v1"] = "how-source-v1"
    session_id: str = Field(min_length=1)
    dog_id: str = Field(min_length=1)
    started_at: AwareDatetime
    ended_at: AwareDatetime
    fixes: tuple[WalkFix, ...]

    @model_validator(mode="after")
    def ordered(self):
        if self.ended_at < self.started_at:
            raise ValueError("session time reversed")
        seqs = [p.client_seq for p in self.fixes]
        if seqs != sorted(set(seqs)):
            raise ValueError("fixes need unique increasing client_seq")
        return self


class HowPolicy(Contract):
    # Keep default and JSON-restored numeric types identical in hashed metrics.
    model_config = ConfigDict(validate_default=True)
    version: Literal["how-geometry-v1"] = "how-geometry-v1"
    max_accuracy_m: float = Field(default=20, gt=0)
    max_speed_mps: float = Field(default=4, gt=0)
    simplify_m: float = Field(default=8, gt=0)
    stay_diameter_m: float = Field(default=20, gt=0)
    stay_min_s: float = Field(default=30, gt=0)
    stay_min_fixes: int = Field(default=5, ge=3)
    stay_progress_step_s: float = Field(default=10, gt=0)
    stay_progress_max_mps: float = Field(default=0.4, gt=0)
    straight_min_m: float = Field(default=40, gt=0)
    turn_leg_min_m: float = Field(default=30, gt=0)
    turn_min_deg: float = Field(default=45, gt=0, lt=180)
    reversal_min_deg: float = Field(default=150, gt=0, le=180)
    retrace_tolerance_m: float = Field(default=10, gt=0)
    retrace_min_m: float = Field(default=40, gt=0)

    @model_validator(mode="after")
    def angles(self):
        if self.reversal_min_deg <= self.turn_min_deg:
            raise ValueError("reversal must exceed turn angle")
        return self


@dataclass(frozen=True)
class _Point:
    fix: WalkFix
    xy: tuple[float, float]
    offset_m: float


def _distance(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _line_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2 if length2 else 0
    t = max(0.0, min(1.0, t))
    return _distance(p, (a[0] + t * dx, a[1] + t * dy))


def _project(fix, origin):
    # Local tangent approximation for short walking routes; units are metres.
    lon_delta = (fix.lng - origin.lng + 180) % 360 - 180
    return (6_371_000 * math.radians(lon_delta) * math.cos(math.radians(origin.lat)),
            6_371_000 * math.radians(fix.lat - origin.lat))


def _chains(trail, policy):
    """Keep canonical breaks; an extra quality rejection also breaks HOW support."""
    runs, run, audit = [], [], []
    prior_chain, run_index = None, 0
    for seg in trail.segments:
        accuracies = [f.accuracy_m for f in (seg.a, seg.b) if f.accuracy_m is not None]
        reason = None
        if accuracies and max(accuracies) > policy.max_accuracy_m:
            reason = "how_accuracy_rejection"
        elif seg.dist / seg.dt > policy.max_speed_mps:
            reason = "how_speed_rejection"
        contiguous = (run and prior_chain == seg.chain_index
                      and run[-1].fix == seg.a)
        if run and (reason or not contiguous):
            runs.append((prior_chain, run_index, run))
            run_index += 1
            run = []
        if reason:
            audit.append({"from_seq": seg.a.client_seq, "to_seq": seg.b.client_seq,
                          "chain_index": seg.chain_index, "reason": reason})
            continue
        origin = run[0].fix if run else seg.a
        if not run:
            run = [_Point(seg.a, (0.0, 0.0), seg.offset_m)]
        run.append(_Point(seg.b, _project(seg.b, origin),
                          seg.offset_m + (seg.dist if seg.moving else 0)))
        prior_chain = seg.chain_index
    if run:
        runs.append((prior_chain, run_index, run))
    return runs, audit


def _stays(points, policy):
    """Maximal greedy windows inside a bounded box diagonal; no GPS-speed guess."""
    windows, i = [], 0
    while i < len(points) - 1:
        low_x = high_x = points[i].xy[0]
        low_y = high_y = points[i].xy[1]
        j = i + 1
        while j < len(points):
            x, y = points[j].xy
            bounds = min(low_x, x), max(high_x, x), min(low_y, y), max(high_y, y)
            if math.hypot(bounds[1] - bounds[0], bounds[3] - bounds[2]) > policy.stay_diameter_m:
                break
            low_x, high_x, low_y, high_y = bounds
            j += 1
        end = j - 1
        duration = (points[end].fix.at - points[i].fix.at).total_seconds()
        coarse = [i]
        for k in range(i + 1, j):
            if (points[k].fix.at - points[coarse[-1]].fix.at).total_seconds() >= (
                policy.stay_progress_step_s
            ):
                coarse.append(k)
        if coarse[-1] != end:
            coarse.append(end)
        progress = sum(_distance(points[a].xy, points[b].xy) for a, b in pairwise(coarse))
        speed = progress / duration if duration else 0
        if (duration >= policy.stay_min_s and j - i >= policy.stay_min_fixes
                and speed <= policy.stay_progress_max_mps):
            middle = ((low_x + high_x) / 2, (low_y + high_y) / 2)
            anchor = min(range(i, j), key=lambda k: _distance(points[k].xy, middle))
            windows.append((i, end, anchor, math.hypot(high_x - low_x, high_y - low_y), speed))
            i = j
        else:
            i += 1
    return windows


def _simplify(points, indices, tolerance):
    """Iterative RDP; retained vertices always reference observed fixes."""
    if len(indices) < 3:
        return indices
    keep, pending = {0, len(indices) - 1}, [(0, len(indices) - 1)]
    while pending:
        a, b = pending.pop()
        if b - a < 2:
            continue
        k = max(range(a + 1, b), key=lambda j: _line_distance(
            points[indices[j]].xy, points[indices[a]].xy, points[indices[b]].xy
        ))
        if _line_distance(points[indices[k]].xy, points[indices[a]].xy,
                          points[indices[b]].xy) > tolerance:
            keep.add(k)
            pending.extend(((a, k), (k, b)))
    return [indices[k] for k in sorted(keep)]


def _angle(a, b, c):
    incoming = b[0] - a[0], b[1] - a[1]
    outgoing = c[0] - b[0], c[1] - b[1]
    cross = incoming[0] * outgoing[1] - incoming[1] * outgoing[0]
    dot = incoming[0] * outgoing[0] + incoming[1] * outgoing[1]
    return math.degrees(math.atan2(cross, dot))  # east/north: positive = left


def _material(points, chain, run, kind, start, end, anchor, metrics):
    window = points[start:end + 1]
    accuracies = [p.fix.accuracy_m for p in window if p.fix.accuracy_m is not None]
    p = points[anchor]
    return {
        "axis": "how", "kind": kind, "status": "candidate",
        "subject": "recording_device",
        "support": {
            "chain_index": chain, "how_run_index": run,
            "from_seq": points[start].fix.client_seq, "to_seq": points[end].fix.client_seq,
            "started_at": points[start].fix.at.astimezone(UTC).isoformat(),
            "ended_at": points[end].fix.at.astimezone(UTC).isoformat(),
            "window_s": (points[end].fix.at - points[start].fix.at).total_seconds(),
            "time_meaning": "observed_support_window",
        },
        "anchor": {
            "client_seq": p.fix.client_seq, "at": p.fix.at.astimezone(UTC).isoformat(),
            "lat": p.fix.lat, "lng": p.fix.lng, "route_offset_m": round(p.offset_m, 3),
        },
        "metrics": metrics,
        "quality": {
            "fix_count": len(window),
            "accuracy_p50_m": statistics.median(accuracies) if accuracies else None,
            "unknown_accuracy_count": len(window) - len(accuracies),
        },
    }


def extract_how(trail: CanonicalTrail, policy: HowPolicy | None = None):
    policy = policy or HowPolicy()
    chains, audit = _chains(trail, policy)
    materials, shape_runs = [], []
    for chain, run, points in chains:
        stays = _stays(points, policy)
        skip = {i for start, end, anchor, _, _ in stays for i in range(start, end + 1)
                if i != anchor}
        accuracies = [p.fix.accuracy_m for p in points if p.fix.accuracy_m is not None]
        tolerance = max(policy.simplify_m, statistics.median(accuracies) if accuracies else 0)
        indices = _simplify(points, [i for i in range(len(points)) if i not in skip], tolerance)
        shape_runs.append({
            "chain_index": chain, "how_run_index": run, "tolerance_m": tolerance,
            "from_seq": points[0].fix.client_seq, "to_seq": points[-1].fix.client_seq,
            "source_fix_count": len(points),
            "vertices": [{"client_seq": points[i].fix.client_seq,
                          "lat": points[i].fix.lat, "lng": points[i].fix.lng} for i in indices],
        })
        for start, end, anchor, diameter, speed in stays:
            materials.append(_material(points, chain, run, "local_stay", start, end, anchor, {
                "bounding_diagonal_m": round(diameter, 2),
                "observed_duration_s": (points[end].fix.at - points[start].fix.at).total_seconds(),
                "coarse_progress_mps": round(speed, 3),
            }))
        for a, b in pairwise(indices):
            length = _distance(points[a].xy, points[b].xy)
            if length >= max(policy.straight_min_m, 2 * tolerance):
                deviation = max(_line_distance(p.xy, points[a].xy, points[b].xy)
                                for p in points[a:b + 1])
                if deviation <= tolerance:
                    materials.append(_material(points, chain, run, "straight_run", a, b, a, {
                        "displacement_m": round(length, 2), "max_deviation_m": round(deviation, 2),
                        "tolerance_m": tolerance,
                    }))
        for a, b, c in zip(indices, indices[1:], indices[2:]):
            incoming = _distance(points[a].xy, points[b].xy)
            outgoing = _distance(points[b].xy, points[c].xy)
            if min(incoming, outgoing) < max(policy.turn_leg_min_m, 2 * tolerance):
                continue
            angle = _angle(points[a].xy, points[b].xy, points[c].xy)
            if abs(angle) < policy.turn_min_deg:
                continue
            direction = ("reverse" if abs(angle) >= policy.reversal_min_deg
                         else "left" if angle > 0 else "right")
            materials.append(_material(points, chain, run, "turn", a, c, b, {
                "direction": direction, "signed_angle_deg": round(angle, 2),
                "incoming_m": round(incoming, 2), "outgoing_m": round(outgoing, 2),
                "tolerance_m": tolerance,
            }))
            if direction == "reverse" and min(incoming, outgoing) >= policy.retrace_min_m:
                # Adjacent-leg retracing only. A parallel return outside this
                # corridor is a reversal, not evidence of following the old path.
                distance = max(_line_distance(p.xy, points[a].xy, points[b].xy)
                               for p in points[b:c + 1])
                corridor = max(policy.retrace_tolerance_m, tolerance)
                if distance <= corridor:
                    materials.append(_material(points, chain, run, "retrace", b, c, b, {
                        "previous_from_seq": points[a].fix.client_seq,
                        "previous_to_seq": points[b].fix.client_seq,
                        "return_displacement_m": round(outgoing, 2),
                        "max_distance_to_previous_leg_m": round(distance, 2),
                        "corridor_m": corridor,
                    }))
    materials.sort(key=lambda m: (m["anchor"]["at"], m["kind"], m["support"]["from_seq"]))
    return {"materials": materials, "shape_runs": shape_runs, "quality_audit": audit}


def build_how(source: HowSource | dict, policy: HowPolicy | None = None):
    source = HowSource.model_validate(source)
    policy = policy or HowPolicy()
    raw = source.model_dump(mode="json")
    computation = compute_facts(source.session_id, source.dog_id, source.started_at,
                                source.ended_at, list(source.fixes))
    extracted = extract_how(computation.trail, policy)
    basis = {
        "source_sha256": payload_hash(raw), "policy": policy.model_dump(mode="json"),
        "calculation_version": computation.trail.calculation_version,
    }
    for material in extracted["materials"]:
        version = payload_hash({"basis": basis, "material": material})
        material["ref"] = {"id": "how:" + version[:16], "version": version}
    return {
        "schema_version": "how-materials-v1", "session_id": source.session_id,
        "evidence_origin": computation.facts.evidence_origin,
        **basis, **extracted, "canonical_quality": computation.trail.quality.to_dict(),
        "limits": {"calibration": "synthetic_only", "where": "not_evaluated",
                   "purpose": "not_inferred", "gradual_curve": "not_classified",
                   "retrace": "adjacent_simplified_legs_only"},
    }


def query_how(catalog, *, at: AwareDatetime, chain_index: int, lookback_s: float = 0):
    """Read candidates for a HOW pool. Does not select, expire or create stamps.

    Geometry needs lookahead. A candidate is available only after its support
    ended, even when its anchor is earlier. Event time and availability differ.
    """
    from datetime import datetime

    if at.tzinfo is None or at.utcoffset() is None or lookback_s < 0:
        raise ValueError("query needs aware time and non-negative lookback")
    found = []
    for material in catalog["materials"]:
        support = material["support"]
        ended = datetime.fromisoformat(support["ended_at"])
        if support["chain_index"] == chain_index and 0 <= (at - ended).total_seconds() <= lookback_s:
            # Thin model-facing material: geometry and coordinates stay in the catalog.
            found.append({"ref": dict(material["ref"]), "kind": material["kind"],
                          "subject": material["subject"], "support": dict(support),
                          "metrics": dict(material["metrics"]),
                          "quality": dict(material["quality"])})
    return found
