"""Observed dwell/pace candidates, separate from user-authored action records.

Offline policy prototype. Geometry supplies dwell and accepted run boundaries;
the existing storyboard speed grouper supplies sustained relative pace changes.
No semantic action inference, model call, or writes to the user's record store.
"""

import statistics
from datetime import UTC
from typing import Literal

from pydantic import ConfigDict, Field

from app.features.storyboard.selection import movement_candidates
from app.features.walk.facts import compute_facts, haversine_m

from .record_envelopes import Contract, payload_hash


class ActionCandidatePolicy(Contract):
    model_config = ConfigDict(validate_default=True)
    version: Literal["observed-action-candidates-v1"] = "observed-action-candidates-v1"
    speed_window_s: float = Field(default=10, ge=5, le=30)
    reference_min_s: float = Field(default=60, ge=30)
    reference_min_windows: int = Field(default=5, ge=3)
    moving_floor_mps: float = Field(default=0.5, gt=0)
    speed_min_delta_mps: float = Field(default=0.3, gt=0)


def _weighted_median(nodes):
    halfway = sum(n["duration_s"] for n in nodes) / 2
    elapsed = 0
    for node in sorted(nodes, key=lambda n: n["speed"]):
        elapsed += node["duration_s"]
        if elapsed >= halfway:
            return node["speed"]
    return None


def _speed_nodes(route, catalog, policy):
    trail = compute_facts(route.session_id, route.dog_id, route.started_at,
                          route.ended_at, list(route.fixes)).trail
    nodes, audit, block = [], [], 0
    segments = iter(trail.segments)
    seg = next(segments, None)
    for run in catalog["shape_runs"]:
        pending, duration = [], 0
        while seg is not None and seg.b.client_seq <= run["from_seq"]:
            seg = next(segments, None)
        run_segments = []
        while seg is not None and seg.a.client_seq < run["to_seq"]:
            run_segments.append(seg)
            seg = next(segments, None)
        for segment in run_segments:
            if (segment.chain_index != run["chain_index"]
                    or not run["from_seq"] <= segment.a.client_seq
                    < segment.b.client_seq <= run["to_seq"]):
                continue
            if segment.a.accuracy_m is None or segment.b.accuracy_m is None:
                audit.append({"from_seq": segment.a.client_seq, "to_seq": segment.b.client_seq,
                              "reason": "unknown_accuracy"})
                pending, duration, block = [], 0, block + 1
                continue
            pending.append(segment)
            duration += segment.dt
            if duration < policy.speed_window_s:
                continue
            points = [pending[0].a] + [s.b for s in pending]
            middle = points[0].at + (points[-1].at - points[0].at) / 2
            anchor = min(points, key=lambda f: abs((f.at - middle).total_seconds()))
            # Endpoint progress suppresses short GPS jitter; it is not path speed
            # around a corner and is deliberately named window displacement speed.
            nodes.append({
                "block": block, "chain_index": run["chain_index"],
                "how_run_index": run["how_run_index"], "points": points,
                "speed": haversine_m(points[0], points[-1]) / duration,
                "duration_s": duration,
                "start_s": (points[0].at - route.started_at).total_seconds(),
                "elapsed_s": (points[-1].at - route.started_at).total_seconds(),
                "anchor": anchor,
            })
            pending, duration = [], 0
        if pending:
            audit.append({"from_seq": pending[0].a.client_seq,
                          "to_seq": pending[-1].b.client_seq, "reason": "short_tail_window"})
        block += 1
    return nodes, audit


def build_action_candidates(route, catalog, policy):
    """Use the same validated route/catalog; output candidates, not selected scenes."""
    if payload_hash(route.model_dump(mode="json")) != catalog["source_sha256"]:
        raise ValueError("candidate catalog belongs to another route")
    candidates, audit = [], []
    for material in catalog["materials"]:
        if material["kind"] != "local_stay":
            continue
        if material["quality"]["unknown_accuracy_count"]:
            audit.append({"material_ref": material["ref"], "reason": "unknown_accuracy"})
            continue
        candidates.append({
            "kind": "observed_dwell", "source_material_ref": material["ref"],
            **{k: material[k] for k in ("support", "anchor", "metrics", "quality")},
        })

    nodes, speed_audit = _speed_nodes(route, catalog, policy)
    reference = [n for n in nodes if n["speed"] >= policy.moving_floor_mps]
    enough = (len(reference) >= policy.reference_min_windows
              and sum(n["duration_s"] for n in reference) >= policy.reference_min_s)
    baseline = _weighted_median(reference) if enough else None
    if baseline is not None:
        # Grouper thresholds are the existing exploratory 0.5x / 1.75x for >=20s.
        gated = [{**n, "speed": n["speed"] if abs(n["speed"] - baseline)
                  >= policy.speed_min_delta_mps else None} for n in nodes]
        for group in movement_candidates(gated, baseline, "session_speed"):
            window = group["movement"]
            members = [n for n in nodes if n["block"] == group["block"]
                       and window["start_s"] <= n["start_s"]
                       and n["elapsed_s"] <= window["end_s"]]
            points = list({p.client_seq: p for n in members for p in n["points"]}.values())
            if len(points) < 5:
                audit.append({"from_seq": points[0].client_seq, "to_seq": points[-1].client_seq,
                              "reason": "insufficient_speed_fixes"})
                continue
            middle = points[0].at + (points[-1].at - points[0].at) / 2
            anchor = min(points, key=lambda f: abs((f.at - middle).total_seconds()))
            candidates.append({
                "kind": "observed_slow" if window["mean_mps"] < baseline else "observed_fast",
                "support": {
                    "chain_index": group["chain_index"], "how_run_index": group["how_run_index"],
                    "from_seq": points[0].client_seq, "to_seq": points[-1].client_seq,
                    "started_at": points[0].at.astimezone(UTC).isoformat(),
                    "ended_at": points[-1].at.astimezone(UTC).isoformat(),
                    "window_s": window["end_s"] - window["start_s"],
                    "time_meaning": "observed_support_window",
                },
                "anchor": {"client_seq": anchor.client_seq, "at": anchor.at.isoformat(),
                           "lat": anchor.lat, "lng": anchor.lng},
                "metrics": {"basis": "window_displacement_speed", "reference": "this_session",
                            "baseline_mps": baseline, "mean_mps": window["mean_mps"],
                            "ratio": window["mean_mps"] / baseline},
                "quality": {"fix_count": len(points), "unknown_accuracy_count": 0,
                            "accuracy_p50_m": statistics.median(p.accuracy_m for p in points)},
            })

    basis = {"route": catalog["source_sha256"], "geometry": catalog["policy"],
             "calculation_version": catalog["calculation_version"],
             "policy": policy.model_dump(mode="json")}
    for candidate in candidates:
        candidate.update({"origin": "derived_observation", "status": "candidate",
                          "subject": "recording_device", "action_meaning": "not_inferred"})
        version = payload_hash({"basis": basis, "candidate": candidate})
        candidate["ref"] = {"id": "observed-action:" + version[:16], "version": version}
    return {
        "schema_version": "observed-action-catalog-v1", "basis": basis,
        "available_at": route.ended_at.isoformat(), "mode": "post_walk",
        "candidates": sorted(candidates, key=lambda c: (c["anchor"]["at"], c["ref"]["id"])),
        "speed_reference": {"status": "available" if enough else "insufficient_observations",
                            "baseline_mps": baseline, "moving_windows": len(reference),
                            "moving_window_s": sum(n["duration_s"] for n in reference),
                            "basis": "duration_weighted_median_of_window_displacement_speed",
                            "slow_ratio_below": 0.5, "fast_ratio_above": 1.75,
                            "change_min_s": 20},
        "audit": audit + speed_audit,
        "limits": {"calibration": "synthetic_only", "meaning": "observation_not_behavior",
                   "speed": "relative_to_this_walk_not_statistical_significance",
                   "corners": "window_displacement_can_underestimate_path_speed"},
    }
