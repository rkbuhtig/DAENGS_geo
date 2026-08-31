"""Android walk export를 로컬에서 네 Paint 후보로 재생한다.

원좌표가 든 입력과 GeoJSON 출력은 레포 밖에만 둔다. 비교 보고서에는 좌표·fix·cell id를
넣지 않는다. 실제 현상을 발견하면 원본을 커밋하지 말고 합성 fixture 회귀로 옮긴다.

    uv run python -m scripts.spikes.territory_paint.cellophane_replay \
      --input C:/dev/walks/device/walk-....json \
      --out C:/dev/walks/cellophane/walk-...

생성된 ``*.geojson``은 ``/cellophane`` 화면의 ``JSON 열기``로 읽는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.features.territory.geojson import dumps_cellophane_geojson
from app.features.territory.paint import (
    NARROW_SMOOTH,
    NARROW_STEP,
    BrushProfile,
    brush_stamp,
    paint_sheet,
)
from app.features.walk.facts import ComputedFacts, Segment, compute_facts
from app.features.walk.models import WalkFix
from app.geo.cells import EARTH_R, cell_area_m2, hex_center_latlng

REPORT_VERSION = 1
LOCAL_READ_M = 25.0
MAX_LOCAL_ANCHORS = 200
REPO_ROOT = Path(__file__).resolve().parents[3]


class ReplaySession(BaseModel):
    """Android export의 session 부분. 제품 모델과 달리 dog_id가 아직 없을 수 있다."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    dog_id: str | None = Field(None, min_length=1, max_length=128)
    started_at: datetime
    ended_at: datetime

    @field_validator("started_at", "ended_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("walk timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def ends_after_start(self) -> ReplaySession:
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must not precede started_at")
        return self


class DeviceExport(BaseModel):
    """WalkSessionExporter format 1. 모르는 필드를 조용히 버리지 않는다."""

    model_config = ConfigDict(extra="forbid")

    format: Literal[1]
    session: ReplaySession
    fixes: list[WalkFix] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_client_sequence(self) -> DeviceExport:
        sequences = [fix.client_seq for fix in self.fixes]
        if len(sequences) != len(set(sequences)):
            raise ValueError("client_seq must be unique in a device export")
        return self


@dataclass(frozen=True)
class ReplayVariant:
    key: str
    radius_u: float
    profile_kind: Literal["step", "smooth"]
    profile: BrushProfile


VARIANTS = (
    ReplayVariant("r8-step", 8.0, "step", NARROW_STEP),
    ReplayVariant("r8-smooth", 8.0, "smooth", NARROW_SMOOTH),
    ReplayVariant("r15-step", 15.0, "step", NARROW_STEP),
    ReplayVariant("r15-smooth", 15.0, "smooth", NARROW_SMOOTH),
)


def parse_export(payload: object) -> tuple[DeviceExport, ComputedFacts]:
    """기기 payload를 검증하고 canonical segment를 한 번만 계산한다."""
    device = DeviceExport.model_validate(payload)
    session = device.session
    fixes = sorted(device.fixes, key=lambda fix: fix.client_seq)
    computed = compute_facts(
        session.id,
        session.dog_id or "local-replay-unassigned",
        session.started_at,
        session.ended_at,
        fixes,
    )
    return device, computed


def _ground_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat = lat2 - lat1
    dlng = math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(h))


def _segment_midpoints(segments: list[Segment]) -> list[tuple[float, float]]:
    """국소 적분 표본. 긴 산책도 측정 자체가 paint보다 비싸지지 않게 200개로 제한한다."""
    if not segments:
        return []
    if len(segments) <= MAX_LOCAL_ANCHORS:
        chosen = segments
    else:
        indexes = {
            round(index * (len(segments) - 1) / (MAX_LOCAL_ANCHORS - 1))
            for index in range(MAX_LOCAL_ANCHORS)
        }
        chosen = [segments[index] for index in sorted(indexes)]
    return [
        ((segment.a.lat + segment.b.lat) / 2, (segment.a.lng + segment.b.lng) / 2)
        for segment in chosen
    ]


def _local_mass_summary(
    occupancy: dict[tuple[int, int], float],
    radius_u: float,
    segments: list[Segment],
    read_m: float,
) -> tuple[int, float, float]:
    anchors = _segment_midpoints(segments)
    centres = [
        (hex_center_latlng(q, r, radius_u), amount)
        for (q, r), amount in occupancy.items()
    ]
    readings = [
        math.fsum(amount for centre, amount in centres if _ground_m(anchor, centre) <= read_m)
        for anchor in anchors
    ]
    if not readings:
        return 0, 0.0, 0.0
    return len(readings), statistics.median(readings), max(readings)


def _gap_brush_overlap_count(computed: ComputedFacts, variant: ReplayVariant) -> int:
    """실제 segment는 없지만 양 끝 붓 때문에 시각적으로 이어질 수 있는 gap 수."""
    count = 0
    for gap in computed.gaps:
        before = {
            cell for cell, _weight in brush_stamp(
                gap.a.lat, gap.a.lng, variant.radius_u, variant.profile
            )
        }
        after = {
            cell for cell, _weight in brush_stamp(
                gap.b.lat, gap.b.lng, variant.radius_u, variant.profile
            )
        }
        count += bool(before & after)
    return count


def _variant_result(
    device: DeviceExport,
    computed: ComputedFacts,
    variant: ReplayVariant,
    read_m: float,
    clock: Callable[[], float],
) -> tuple[dict[str, object], str]:
    started = clock()
    sheet = paint_sheet(
        device.session.id,
        device.session.started_at,
        computed.segments,
        variant.radius_u,
        variant.profile,
    )
    paint_ms = (clock() - started) * 1000

    started = clock()
    geojson = dumps_cellophane_geojson(sheet, computed.segments)
    serialize_ms = (clock() - started) * 1000
    anchors, local_median, local_max = _local_mass_summary(
        sheet.occupancy, variant.radius_u, computed.segments, read_m
    )
    occupancy_mass = math.fsum(sheet.occupancy.values())
    top_ten = sorted(sheet.occupancy.values(), reverse=True)[:10]
    support_area = math.fsum(
        cell_area_m2(variant.radius_u, hex_center_latlng(q, r, variant.radius_u)[0])
        for q, r in sheet.occupancy
    )
    filename = f"cellophane-{variant.key}.geojson"
    return {
        "key": variant.key,
        "geojson_file": filename,
        "radius_u": variant.radius_u,
        "profile_kind": variant.profile_kind,
        "profile_name": variant.profile.name,
        "profile_fp": variant.profile.fingerprint,
        "paint_fp": sheet.paint_fp,
        "sample_step_m": sheet.sample_step_m,
        "cell_count": len(sheet.occupancy),
        "payload_bytes": len(geojson.encode("utf-8")),
        "paint_ms": paint_ms,
        "serialize_ms": serialize_ms,
        "support_area_m2": support_area,
        "local_anchor_count": anchors,
        "local_occupancy_p50_s": local_median,
        "local_occupancy_max_s": local_max,
        "top10_mass_share": math.fsum(top_ten) / occupancy_mass if occupancy_mass else 0.0,
        "gap_brush_overlap_count": _gap_brush_overlap_count(computed, variant),
        "occupancy_mass_s": occupancy_mass,
        "mass_error_s": occupancy_mass - math.fsum(s.dt for s in computed.segments),
    }, geojson


def replay_export(
    payload: object,
    *,
    local_read_m: float = LOCAL_READ_M,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[dict[str, object], dict[str, str]]:
    """한 export를 네 후보로 비교한다. 보고서는 위치를 복원할 필드를 갖지 않는다."""
    if not math.isfinite(local_read_m) or local_read_m <= 0:
        raise ValueError("local_read_m must be a finite positive number")
    device, computed = parse_export(payload)
    source_segment_s = math.fsum(segment.dt for segment in computed.segments)
    rows: list[dict[str, object]] = []
    outputs: dict[str, str] = {}
    for variant in VARIANTS:
        row, geojson = _variant_result(
            device, computed, variant, local_read_m, clock
        )
        rows.append(row)
        outputs[row["geojson_file"]] = geojson

    chains = {segment.chain_index for segment in computed.segments}
    report = {
        "report_version": REPORT_VERSION,
        "input": {
            "format": device.format,
            "session_id": device.session.id,
            "input_sha256": hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "fix_count": len(device.fixes),
            "evidence_origin": computed.facts.evidence_origin,
            "source_segment_s": source_segment_s,
            "segment_count": len(computed.segments),
            "chain_count": len(chains),
            "gap_count": len(computed.gaps),
            "quality": computed.quality.to_dict(),
        },
        "comparison": {
            "local_read_m": local_read_m,
            "variants": rows,
        },
    }
    return report, outputs


def _outside_repo(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise ValueError(f"{label} must be outside the repository: {resolved}")
    return resolved


def write_outputs(out: Path, report: dict[str, object], outputs: dict[str, str]) -> None:
    """기존 측정을 덮지 않는다. 별도 빈 폴더를 줘야 한다."""
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"output directory is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for filename, geojson in outputs.items():
        (out / filename).write_text(geojson + "\n", encoding="utf-8")


def _print_report(report: dict[str, object]) -> None:
    source = report["input"]
    comparison = report["comparison"]
    print(
        f"session {source['session_id']} · fix {source['fix_count']} · "
        f"segment {source['segment_count']} · chain {source['chain_count']} · "
        f"gap {source['gap_count']}"
    )
    for row in comparison["variants"]:
        print(
            f"  {row['key']:<10} {row['cell_count']:>5} cells · "
            f"{row['payload_bytes']:>8} bytes · paint {row['paint_ms']:>7.2f}ms · "
            f"local p50 {row['local_occupancy_p50_s']:>7.2f}s · "
            f"top10 {row['top10_mass_share']:>6.1%} · "
            f"mass error {row['mass_error_s']:.6f}s"
        )


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, required=True, help="walk_bundle device export")
    parser.add_argument("--out", type=Path, required=True, help="빈 출력 폴더 (레포 밖)")
    parser.add_argument("--local-read-m", type=float, default=LOCAL_READ_M)
    args = parser.parse_args(argv)

    try:
        source = _outside_repo(args.input, "input")
        out = _outside_repo(args.out, "output")
        payload = json.loads(source.read_text(encoding="utf-8"))
        report, outputs = replay_export(payload, local_read_m=args.local_read_m)
        write_outputs(out, report, outputs)
    except (FileExistsError, OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    _print_report(report)
    print(f"written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
