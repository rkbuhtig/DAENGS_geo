"""Deterministic tap capture and diary comparisons. Truth never supplies a pin position."""
from __future__ import annotations

import math
from collections import Counter
from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scripts.sim.walk.bundle import ScenarioArtifacts, build_scenario_from_spec
from scripts.sim.walk.lab import build_lab_payload
from scripts.sim.walk.spec import WalkTraceScenarioSpec
from scripts.spikes.storyboard_and_regions.sources import fingerprint

LABELS = {"sniffing": "킁킁", "excretion": "배설", "barking": "짖기", "note": "특별한 순간"}


class Tap(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=100)
    at_s: float = Field(ge=0)
    code: Literal["sniffing", "excretion", "barking", "note"]
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def valid_note(self):
        self.note = self.note.strip()
        if (self.code == "note") != bool(self.note):
            raise ValueError("A special moment requires a memo; behavior taps cannot carry a memo")
        return self


class Experiment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: WalkTraceScenarioSpec
    taps: list[Tap] = Field(default_factory=list, max_length=200)
    policy: Literal["common", "behavior"] = "behavior"
    scene_limit: int = Field(default=5, ge=2, le=20)
    fetch: bool = False

    @model_validator(mode="after")
    def unique_ids(self):
        if len({tap.id for tap in self.taps}) != len(self.taps):
            raise ValueError("Duplicate entry ids")
        return self


def distance(a, b):
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlon = lat2-lat1, math.radians(b[1]-a[1])
    h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 12_742_000 * math.asin(min(1, math.sqrt(h)))


def capture(artifacts: ScenarioArtifacts, tap: Tap):
    if tap.at_s > artifacts.derived["truth_duration_s"]:
        raise ValueError("Tap is beyond walk end")
    # Select newest CAPTURE among fixes DELIVERED by tap time, ignoring duplicates.
    delivered = [e for e in artifacts.delivery["events"] if e["delivered_elapsed_s"] <= tap.at_s]
    latest = max(delivered, key=lambda e: e["captured_elapsed_s"], default=None)
    sample = next((s for s in artifacts.trace["samples"]
                   if latest and s["sample_id"] == latest["sample_id"]), None)
    fix = sample["observed_fix"] if sample else None
    age = tap.at_s - latest["captured_elapsed_s"] if latest else None
    reason = "no_delivered_fix"
    if fix:
        reason = ("stale_fix" if age > 15 else "low_accuracy"
                  if fix["accuracy_m"] is None or fix["accuracy_m"] > 50 else "available")
    # Lab thresholds are explicit experiment parameters, not a claimed app-policy mirror.
    location = ({"lat": fix["lat"], "lng": fix["lng"], "captured_at": fix["at"],
                 "accuracy_m": fix["accuracy_m"]} if reason == "available" else None)
    accepted = tap.code == "note" or location is not None
    elapsed_distance = sum(s.dist for s in artifacts.computed.trail.segments
                           if s.moving and (s.b.at-artifacts.observed.started_at).total_seconds()
                           <= tap.at_s)
    return {
        "id": tap.id, "vocabulary_version": "walk-behavior-v1",
        "kind": "note" if tap.code == "note" else "behavior",
        "behavior_code": None if tap.code == "note" else tap.code,
        "label": LABELS[tap.code], "note": tap.note or None,
        "pet_id": None if tap.code == "note" else artifacts.scenario["dog_id"],
        "recorded_at": (artifacts.observed.started_at + timedelta(seconds=tap.at_s)).isoformat(),
        "elapsed_s": tap.at_s, "accepted_distance_m": round(elapsed_distance),
        "location": location, "accepted": accepted, "location_status": reason,
        "fix_age_s": age, "sample_id": latest["sample_id"] if latest else None,
    }


def prepare(experiment: Experiment):
    artifacts = build_scenario_from_spec(experiment.scenario)
    entries = [capture(artifacts, tap) for tap in sorted(experiment.taps, key=lambda t: (t.at_s, t.id))]
    return artifacts, entries


def summarize(experiment, artifacts, entries, contexts):
    live = [e for e in entries if e["accepted"]]
    counts = Counter(e["behavior_code"] for e in live if e["kind"] == "behavior")
    facts = artifacts.computed.facts.model_dump(mode="json")
    rows = []
    for entry in live:
        text = entry["note"] if entry["kind"] == "note" else f'{entry["label"]} 기록'
        context = contexts.get(entry["id"], {"status": "not_requested", "facts": []})
        rows.append({"entry_id": entry["id"], "elapsed_s": entry["elapsed_s"],
                     "text": text, "context": context,
                     "routine": f'산책 {int(entry["elapsed_s"]//60)}분 경과 · 수용 이동거리 '
                                f'{entry["accepted_distance_m"]}m'})
    # Even spacing is a comparison baseline, not a significance ranking.
    budget = max(0, experiment.scene_limit-2)
    selected = (list(range(len(rows))) if len(rows) <= budget else
                sorted({round(i*(len(rows)-1)/max(1, budget-1)) for i in range(budget)}))
    scenes = [{"text": "산책 시작", "entry_id": None}]
    scenes += [rows[i] for i in selected]
    scenes += [{"text": f'산책 종료 · 수용 이동거리 {round(facts["moving_distance_m"])}m',
                "entry_id": None}]
    revision = fingerprint({"scenario": artifacts.scenario, "entries": live})
    diagnostics = []
    origin = artifacts.scenario["origin"]
    for entry in live:
        if not entry["location"]:
            continue
        sample = next(s for s in artifacts.trace["samples"]
                      if s["sample_id"] == entry["sample_id"])
        truth = sample["truth"]
        truth_point = (origin["lat"] + math.degrees(truth["north_m"]/6_371_000),
                       origin["lng"] + math.degrees(truth["east_m"] / (
                           6_371_000*math.cos(math.radians(origin["lat"])))))
        loc = entry["location"]
        diagnostics.append({"entry_id": entry["id"],
                            "capture_position_error_m": round(distance(
                                truth_point, (loc["lat"], loc["lng"])), 2),
                            "fix_age_s": entry["fix_age_s"]})
    return {
        "format": "walk-record-lab-result-v1", "synthetic": True,
        "policy": experiment.policy, "capture_policy": {"max_age_s": 15, "max_accuracy_m": 50},
        "evaluation_only": {"anchor_errors": diagnostics,
                            "note": "Truth at GPS capture time; never used for context or profile"},
        "source_revision": revision, "entries": entries, "rows": rows, "scenes": scenes,
        "result_revision": fingerprint({"source_revision": revision, "contexts": contexts,
                                        "policy": experiment.policy,
                                        "scene_limit": experiment.scene_limit}),
        "omitted_entry_ids": [r["entry_id"] for i, r in enumerate(rows) if i not in selected],
        "profile": {"name": "산책 기록 프로필", "walk_count": 1,
                    "counts": {code: {"entry_count": counts[code],
                                      "recorded_walk_count": int(counts[code] > 0)}
                               for code in LABELS if code != "note"},
                    "evidence_ids": [e["id"] for e in live if e["kind"] == "behavior"]},
        "trace": build_lab_payload(artifacts),
    }
