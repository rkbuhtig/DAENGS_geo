"""Generate observed walks, run geo calculations and attach saved environment responses."""

import argparse
import math
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path

from scripts.sim.walk.bundle import build_scenario_from_spec
from scripts.sim.walk.spec import WalkTraceScenarioSpec

from .geo_adapter import QueryPolicy, build_evidence
from .storage import digest, read, save

DEFAULT_RECIPE = Path(__file__).parent / "fixtures/acquisition.json"


def make_spec(recipe, settings, session_id, started_at, seed):
    origin = recipe["origin"]
    points = []
    for name in settings["route"]:
        point = recipe["points"][name]
        if "xy" in point:
            points.append(point["xy"])
        else:
            lat, lng = point["latlng"]
            points.append(
                [
                    math.radians(lng - origin["lng"])
                    * 6_371_000
                    * math.cos(math.radians(origin["lat"])),
                    math.radians(lat - origin["lat"]) * 6_371_000,
                ]
            )
    offsets = [0.0]
    for a, b in pairwise(points):
        offsets.append(offsets[-1] + math.dist(a, b))
    return WalkTraceScenarioSpec.model_validate(
        {
            "format": "walk-trace-scenario-v1",
            "seed": seed,
            "session_id": session_id,
            "dog_id": recipe["dog_id"],
            "started_at": started_at,
            "origin": origin,
            "route": {"name": "fixture-route", "points_xy": points},
            "motion": {
                "name": "fixture-motion",
                "base_speed_mps": settings["base_speed_mps"],
                "holds": [
                    {"progress_m": offsets[h["waypoint_index"]], "duration_s": h["duration_s"]}
                    for h in settings["holds"]
                ],
            },
            "sensor": recipe["sensor"],
        }
    )


def generate_observations(recipe, out):
    """Only observed exports and separately authored pins cross into the adapter."""

    def generate(settings, session_id, at, seed):
        spec = make_spec(recipe, settings, session_id, at, seed)
        artifacts = build_scenario_from_spec(spec)
        save(out / "evaluation" / session_id / "scenario.json", artifacts.scenario)
        save(out / "evaluation" / session_id / "manifest.json", artifacts.manifest)
        save(out / "evaluation" / session_id / "truth.json", artifacts.truth)
        observed = artifacts.observed.to_export()
        save(out / "observations" / f"{session_id}.json", observed)
        return observed

    current_settings = recipe["current"]
    start = datetime.fromisoformat(current_settings["started_at"])
    current = generate(current_settings, "diary-current-01", start, current_settings["seed"])
    history = []
    for group in recipe["history_groups"]:
        for _ in range(group["count"]):
            index = len(history) + 1
            speeds = recipe["history_speed_mps"]
            settings = {**group, "base_speed_mps": speeds[(index - 1) % len(speeds)]}
            history.append(
                generate(
                    settings,
                    f"diary-history-{index:02d}",
                    start - timedelta(days=index),
                    current_settings["seed"] + index,
                )
            )
    pins = []
    for pin in recipe["pins"]:
        at = start + timedelta(seconds=pin["elapsed_s"])
        if not start <= at <= datetime.fromisoformat(current["session"]["ended_at"]):
            raise ValueError("fixture pin falls outside generated session")
        fix = min(
            current["fixes"],
            key=lambda f: abs((datetime.fromisoformat(f["at"]) - at).total_seconds()),
        )
        pins.append(
            {
                "id": pin["id"],
                "at": at.isoformat(),
                "type": pin["type"],
                "memo": pin["memo"],
                "lat": fix["lat"],
                "lng": fix["lng"],
                "location_from_client_seq": fix["client_seq"],
                "location_observed_at": fix["at"],
                "recorded_by": "synthetic_guardian_input",
            }
        )
    save(out / "pins.json", pins)
    return current, history, pins


def acquire(recipe, cache_dir: Path, out: Path):
    if recipe["format"] != "diary-acquisition-v1":
        raise ValueError("unsupported acquisition recipe")
    policy = QueryPolicy.model_validate(recipe["query_policy"])
    snapshots = [read(cache_dir / name) for name in recipe["environment_snapshots"]]
    if out.exists() and any(out.iterdir()):
        raise ValueError("acquisition requires a new empty output directory")
    out.mkdir(parents=True, exist_ok=True)
    save(out / "evaluation" / "recipe.json", recipe)
    current, history, pins = generate_observations(recipe, out)
    # Neither artifacts.derived (contains truth_duration_s) nor scenario/manifest is forwarded.
    evidence, audit = build_evidence(current, history, pins, policy, snapshots)
    save(out / "evidence.json", evidence.model_dump(mode="json"))
    save(out / "calculation_audit.json", audit)
    save(
        out / "acquisition_receipt.json",
        {
            "recipe_sha256": digest(recipe),
            "current_observation_sha256": digest(current),
            "history_observation_sha256": digest(history),
            "pins_sha256": digest(pins),
            "environment_snapshots": [
                {"file": name, "snapshot_sha256": digest(snapshot)}
                for name, snapshot in zip(recipe["environment_snapshots"], snapshots, strict=True)
            ],
            "evidence_sha256": digest(evidence.model_dump(mode="json")),
            "history_count": len(history),
            "piece_count": len(evidence.pieces),
            "truth_location": "evaluation/",
            "llm_input": "evidence.json",
        },
    )
    lines = [
        "# geo 계산으로 만든 산책 입력",
        "",
        "GPS·행동핀은 합성, 환경은 저장된 실제 응답이다.",
        "",
        f"시작: {evidence.started_at.isoformat()} / 종료: {evidence.ended_at.isoformat()}",
        f"과거 산책: {len(history)}개 / 자료 조각: {len(evidence.pieces)}개",
        "",
        "## 이번 세션의 계산된 시간축",
        "",
        "| 구간 | 시작 | 종료 | moving 분류 | 관측 거리(m) |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {r['id']} | {r['started_at']} | {r['ended_at']} | "
        f"{r['moving_classification']} | {r['observed_path_m']:.2f} |"
        for r in audit["timeline"]
    ]
    lines += [
        "",
        "## 과거 공간 경향의 실제 집계",
        "",
        "| 조각 | 등장 산책 / 분모 | 비율 | 공간에 배분된 관측 초 | 이번 반경 내 관측 구간 수 |",
        "|---|---|---|---|---|",
    ]
    for reading in audit["spatial_readings"]:
        v = reading["value"]
        lines.append(
            f"| {reading['piece_id']} | {v['appeared_walks']}/{v['selected_walks']} | "
            f"{v['appearance_ratio']} | {v['occupancy_mass_s']:.2f} | "
            f"{len(v['current_observed_passages'])} |"
        )
    lines += ["", "## 환경 자료의 연결", ""]
    lines += [
        f"- {p.id}: {p.measurement_status}" for p in evidence.pieces if p.kind == "environment"
    ]
    (out / "INPUT_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return evidence, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, default=DEFAULT_RECIPE)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    evidence, audit = acquire(read(args.recipe), args.cache_dir, args.out)
    print(
        f"prepared {len(evidence.pieces)} pieces from observed GPS; "
        f"selected {len(audit['selected_session_ids'])} historical walks"
    )


if __name__ == "__main__":
    main()
