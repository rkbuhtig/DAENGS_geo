"""고정 경로 모양에서 WalkDiaryRoute 후보를 재현해 비교한다."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from scripts.sim.walk.bundle import build_scenario_from_spec
from scripts.sim.walk.spec import (
    MotionSpec,
    OriginSpec,
    RouteSpec,
    SensorSpec,
    WalkTraceScenarioSpec,
)
from scripts.spikes.walk_diary_route.projector import build_diary_route_experiment

ROUTES = {
    "outbound-600m": ((0.0, 0.0), (600.0, 0.0)),
    "closed-loop-600m": (
        (0.0, 0.0),
        (150.0, 0.0),
        (150.0, 150.0),
        (0.0, 150.0),
        (0.0, 0.0),
    ),
    "mid-walk-home-revisit": (
        (0.0, 0.0),
        (160.0, 0.0),
        (0.0, 0.0),
        (0.0, 160.0),
        (160.0, 160.0),
    ),
}


def measure_scenarios() -> list[dict[str, object]]:
    rows = []
    for index, (name, points) in enumerate(ROUTES.items()):
        spec = WalkTraceScenarioSpec(
            seed=index,
            session_id=f"diary-route-{name}",
            dog_id="experiment-dog",
            started_at=datetime(2026, 9, 3, 8, tzinfo=UTC),
            origin=OriginSpec(lat=37.4979, lng=127.0276),
            route=RouteSpec(name=name, points_xy=points),
            motion=MotionSpec(name="steady", base_speed_mps=1.2),
            sensor=SensorSpec(kind="perfect", sample_interval_s=5, accuracy_m=3),
        )
        artifacts = build_scenario_from_spec(spec)
        experiment = build_diary_route_experiment(
            artifacts.computed.trail, artifacts.computed.facts.started_at
        )
        for candidate in experiment["candidates"]:
            metrics = candidate["metrics"]
            rows.append(
                {
                    "scenario": name,
                    "profile": candidate["profile"]["id"],
                    "status": candidate["status"],
                    "vertices": metrics.get("output_vertex_count"),
                    "bytes": metrics.get("encoded_json_bytes"),
                    "retained_distance_pct": metrics.get("retained_distance_pct"),
                    "fidelity_p95_m": metrics.get("fidelity_p95_m"),
                    "start_exposure_m": metrics.get("nearest_geometry_to_start_m"),
                    "fragments": metrics.get("visible_fragment_count"),
                }
            )
    return rows


def _markdown(rows: list[dict[str, object]]) -> str:
    headings = (
        "scenario",
        "profile",
        "status",
        "vertices",
        "bytes",
        "retained_distance_pct",
        "fidelity_p95_m",
        "start_exposure_m",
        "fragments",
    )
    output = ["| " + " | ".join(headings) + " |", "|" + "---|" * len(headings)]
    output.extend("| " + " | ".join(str(row[key]) for key in headings) + " |" for row in rows)
    return "\n".join(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    rows = measure_scenarios()
    print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else _markdown(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
