"""walk trace scenario를 Android 내부/GPX/ADB가 읽는 capture-time replay로 바꾼다.

    uv run python -m scripts.sim.walk.android_replay \
      --spec scripts/sim/walk/examples/sniff-and-go.json \
      --out C:/dev/walk-replay/sniff-and-go

`--play`는 실행 중인 Android Emulator에 observed 좌표를 시간 순서대로 보낸다. 위치 source
경계이므로 delivery 지연·역순·중복은 적용하지 않으며, chain break는 앱의 pause/resume 명령이
필요해 기본적으로 ADB 재생을 거부한다.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from scripts.sim.walk.bundle import ScenarioArtifacts, build_scenario_from_spec
from scripts.sim.walk.spec import WalkTraceScenarioSpec

ANDROID_REPLAY_FORMAT = "walk-location-replay-v1"
GPX_NAMESPACE = "http://www.topografix.com/GPX/1/1"
DAENGS_GPX_NAMESPACE = "https://daengs.dev/gpx/1"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class AndroidReplaySample(_StrictModel):
    sample_id: str = Field(min_length=1)
    source_client_seq: int = Field(ge=0)
    source_chain_index: int = Field(ge=0)
    captured_offset_ms: int = Field(ge=0)
    delay_from_previous_ms: int = Field(ge=0)
    elapsed_realtime_offset_nanos: int = Field(ge=0)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(None, ge=0)
    is_mock: Literal[True] = True


class AndroidReplayControlEvent(_StrictModel):
    type: Literal["chain_break"] = "chain_break"
    at_offset_ms: int = Field(ge=0)
    before_sample_id: str = Field(min_length=1)
    after_sample_id: str = Field(min_length=1)
    from_chain_index: int = Field(ge=0)
    to_chain_index: int = Field(ge=0)


class AndroidReplayReceipt(_StrictModel):
    source_truth_sample_count: int = Field(ge=0)
    emitted_location_sample_count: int = Field(ge=0)
    omitted_missing_sample_count: int = Field(ge=0)
    source_delivery_event_count: int = Field(ge=0)
    delivery_applied: Literal[False] = False
    adb_unrepresentable_fields: tuple[str, ...]
    gpx_extension_fields: tuple[str, ...]


class AndroidReplayContract(_StrictModel):
    format: Literal[ANDROID_REPLAY_FORMAT] = ANDROID_REPLAY_FORMAT
    scenario_id: str = Field(min_length=1)
    source_scenario_format: str = Field(min_length=1)
    source_trace_format: str = Field(min_length=1)
    source_started_at: datetime
    speed_semantics: Literal["relative capture offsets; consumer chooses multiplier"] = (
        "relative capture offsets; consumer chooses multiplier"
    )
    samples: tuple[AndroidReplaySample, ...] = Field(min_length=2)
    control_events: tuple[AndroidReplayControlEvent, ...] = ()
    receipt: AndroidReplayReceipt

    @field_validator("source_started_at")
    @classmethod
    def started_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("source_started_at must include a timezone")
        return value

    @model_validator(mode="after")
    def timeline_and_receipt_are_consistent(self) -> AndroidReplayContract:
        previous_offset_ms = 0
        previous_sample: AndroidReplaySample | None = None
        expected_controls = []
        sample_ids = set()
        for index, sample in enumerate(self.samples):
            if sample.sample_id in sample_ids:
                raise ValueError("sample_id must be unique")
            sample_ids.add(sample.sample_id)
            if index and sample.captured_offset_ms <= previous_offset_ms:
                raise ValueError("captured offsets must be strictly increasing")
            if (
                previous_sample is not None
                and sample.source_client_seq <= previous_sample.source_client_seq
            ):
                raise ValueError("source client sequences must be strictly increasing")
            if (
                previous_sample is not None
                and sample.source_chain_index < previous_sample.source_chain_index
            ):
                raise ValueError("source chain indexes must not decrease")
            if sample.delay_from_previous_ms != sample.captured_offset_ms - previous_offset_ms:
                raise ValueError("delay_from_previous_ms must match captured offsets")
            if sample.elapsed_realtime_offset_nanos != sample.captured_offset_ms * 1_000_000:
                raise ValueError("elapsed realtime offset must match the capture offset")
            if (
                previous_sample is not None
                and sample.source_chain_index != previous_sample.source_chain_index
            ):
                expected_controls.append(
                    AndroidReplayControlEvent(
                        at_offset_ms=sample.captured_offset_ms,
                        before_sample_id=previous_sample.sample_id,
                        after_sample_id=sample.sample_id,
                        from_chain_index=previous_sample.source_chain_index,
                        to_chain_index=sample.source_chain_index,
                    )
                )
            previous_offset_ms = sample.captured_offset_ms
            previous_sample = sample
        if tuple(expected_controls) != self.control_events:
            raise ValueError("control_events must match sample chain transitions")
        if self.receipt.emitted_location_sample_count != len(self.samples):
            raise ValueError("receipt emitted count must match samples")
        if (
            self.receipt.source_truth_sample_count
            != len(self.samples) + self.receipt.omitted_missing_sample_count
        ):
            raise ValueError("receipt truth count must equal emitted plus missing samples")
        return self


@dataclass(frozen=True)
class AndroidReplayArtifacts:
    replay: AndroidReplayContract
    gpx: str


def _observed_rows(artifacts: ScenarioArtifacts) -> list[tuple[int, dict[str, object]]]:
    return [
        (index, row)
        for index, row in enumerate(artifacts.trace["samples"])
        if row["observed_fix"] is not None
    ]


def build_android_replay(artifacts: ScenarioArtifacts) -> AndroidReplayContract:
    """truth/fault 설명을 빼고 Android LocationSource가 필요한 관측 capture만 만든다."""
    observed_rows = _observed_rows(artifacts)
    samples = []
    controls = []
    previous_offset_ms = 0
    previous_sample: AndroidReplaySample | None = None
    for _, row in observed_rows:
        fix = row["observed_fix"]
        captured_offset_ms = round(float(row["captured_elapsed_s"]) * 1_000)
        sample = AndroidReplaySample(
            sample_id=str(row["sample_id"]),
            source_client_seq=fix["client_seq"],
            source_chain_index=fix["chain_index"],
            captured_offset_ms=captured_offset_ms,
            delay_from_previous_ms=captured_offset_ms - previous_offset_ms,
            elapsed_realtime_offset_nanos=captured_offset_ms * 1_000_000,
            latitude=fix["lat"],
            longitude=fix["lng"],
            accuracy_m=fix["accuracy_m"],
            is_mock=True,
        )
        if (
            previous_sample is not None
            and sample.source_chain_index != previous_sample.source_chain_index
        ):
            controls.append(
                AndroidReplayControlEvent(
                    at_offset_ms=sample.captured_offset_ms,
                    before_sample_id=previous_sample.sample_id,
                    after_sample_id=sample.sample_id,
                    from_chain_index=previous_sample.source_chain_index,
                    to_chain_index=sample.source_chain_index,
                )
            )
        samples.append(sample)
        previous_sample = sample
        previous_offset_ms = captured_offset_ms

    trace_rows = artifacts.trace["samples"]
    return AndroidReplayContract(
        scenario_id=str(artifacts.scenario["session_id"]),
        source_scenario_format=str(artifacts.scenario["format"]),
        source_trace_format=str(artifacts.trace["format"]),
        source_started_at=artifacts.computed.facts.started_at,
        samples=tuple(samples),
        control_events=tuple(controls),
        receipt=AndroidReplayReceipt(
            source_truth_sample_count=len(trace_rows),
            emitted_location_sample_count=len(samples),
            omitted_missing_sample_count=sum(row["observed_fix"] is None for row in trace_rows),
            source_delivery_event_count=len(artifacts.delivery["events"]),
            adb_unrepresentable_fields=(
                "accuracy_m",
                "is_mock (the emulator build identity remains the app-side mock evidence)",
                "control_events (require app pause/resume)",
                "delivery (belongs after capture)",
            ),
            gpx_extension_fields=(
                "sample_id",
                "accuracy_m",
                "source_chain_index",
                "is_mock",
            ),
        ),
    )


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_gpx(artifacts: ScenarioArtifacts) -> str:
    """Android Studio가 읽는 GPX. missing/chain 경계마다 trkseg를 나눠 직선 보간을 막는다."""
    ET.register_namespace("", GPX_NAMESPACE)
    ET.register_namespace("daengs", DAENGS_GPX_NAMESPACE)
    root = ET.Element(
        f"{{{GPX_NAMESPACE}}}gpx",
        {"version": "1.1", "creator": "DAENGS walk trace adapter"},
    )
    track = ET.SubElement(root, f"{{{GPX_NAMESPACE}}}trk")
    ET.SubElement(track, f"{{{GPX_NAMESPACE}}}name").text = str(artifacts.scenario["session_id"])
    started_at = artifacts.computed.facts.started_at
    segment: ET.Element | None = None
    previous_index: int | None = None
    previous_chain: int | None = None
    for trace_index, row in _observed_rows(artifacts):
        fix = row["observed_fix"]
        chain = int(fix["chain_index"])
        if (
            segment is None
            or previous_index is None
            or trace_index != previous_index + 1
            or chain != previous_chain
        ):
            segment = ET.SubElement(track, f"{{{GPX_NAMESPACE}}}trkseg")
        point = ET.SubElement(
            segment,
            f"{{{GPX_NAMESPACE}}}trkpt",
            {"lat": f"{float(fix['lat']):.9f}", "lon": f"{float(fix['lng']):.9f}"},
        )
        captured_at = started_at + timedelta(seconds=float(row["captured_elapsed_s"]))
        ET.SubElement(point, f"{{{GPX_NAMESPACE}}}time").text = _iso_utc(captured_at)
        extensions = ET.SubElement(point, f"{{{GPX_NAMESPACE}}}extensions")
        ET.SubElement(extensions, f"{{{DAENGS_GPX_NAMESPACE}}}sampleId").text = str(
            row["sample_id"]
        )
        if fix["accuracy_m"] is not None:
            ET.SubElement(
                extensions,
                f"{{{DAENGS_GPX_NAMESPACE}}}accuracyMeters",
            ).text = str(fix["accuracy_m"])
        ET.SubElement(
            extensions,
            f"{{{DAENGS_GPX_NAMESPACE}}}sourceChainIndex",
        ).text = str(chain)
        ET.SubElement(extensions, f"{{{DAENGS_GPX_NAMESPACE}}}isMock").text = "true"
        previous_index = trace_index
        previous_chain = chain

    ET.indent(root, space="  ")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + ET.tostring(
            root,
            encoding="unicode",
            short_empty_elements=True,
        )
        + "\n"
    )


def build_android_replay_artifacts(artifacts: ScenarioArtifacts) -> AndroidReplayArtifacts:
    return AndroidReplayArtifacts(
        replay=build_android_replay(artifacts),
        gpx=build_gpx(artifacts),
    )


def write_android_replay(out: Path, artifacts: AndroidReplayArtifacts) -> None:
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"output directory is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "android-replay.json").write_text(
        json.dumps(
            artifacts.replay.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "android-route.gpx").write_text(artifacts.gpx, encoding="utf-8")


CommandRunner = Callable[[Sequence[str]], None]
Sleeper = Callable[[float], None]
Clock = Callable[[], float]


def _run_command(command: Sequence[str]) -> None:
    subprocess.run(command, check=True)


def _adb_fix_command(prefix: Sequence[str], sample: AndroidReplaySample) -> list[str]:
    return [
        *prefix,
        "emu",
        "geo",
        "fix",
        f"{sample.longitude:.9f}",
        f"{sample.latitude:.9f}",
    ]


def _validate_adb_replay(
    contract: AndroidReplayContract,
    *,
    speed_multiplier: float,
    prime_wait_s: float,
    allow_unapplied_controls: bool,
) -> None:
    if not math.isfinite(speed_multiplier) or speed_multiplier <= 0:
        raise ValueError("speed_multiplier must be finite and positive")
    if not math.isfinite(prime_wait_s) or prime_wait_s < 0:
        raise ValueError("prime_wait_s must be finite and non-negative")
    if contract.control_events and not allow_unapplied_controls:
        raise ValueError(
            "ADB coordinates cannot apply chain breaks; replay pause/resume controls separately "
            "or pass allow_unapplied_controls=True"
        )


def replay_with_adb(
    replay: AndroidReplayContract | dict[str, object],
    *,
    speed_multiplier: float = 1.0,
    adb_binary: str = "adb",
    serial: str | None = None,
    prime_wait_s: float = 0.0,
    allow_unapplied_controls: bool = False,
    runner: CommandRunner = _run_command,
    sleeper: Sleeper = time.sleep,
    clock: Clock = time.monotonic,
) -> int:
    """observed capture를 emulator console에 흘린다. 경도/위도 순서를 이 경계가 소유한다."""
    contract = (
        replay
        if isinstance(replay, AndroidReplayContract)
        else AndroidReplayContract.model_validate(replay)
    )
    _validate_adb_replay(
        contract,
        speed_multiplier=speed_multiplier,
        prime_wait_s=prime_wait_s,
        allow_unapplied_controls=allow_unapplied_controls,
    )
    prefix = [adb_binary]
    if serial:
        prefix.extend(("-s", serial))
    if prime_wait_s:
        # Fused가 이전 cached fix를 먼저 내지 않도록 시작점을 잡고, 그 사이 사용자가 산책
        # 시작을 누른다. 대기 뒤 첫 표본부터 다시 보내므로 replay capture 시간축은 그때 시작한다.
        runner(_adb_fix_command(prefix, contract.samples[0]))
        sleeper(prime_wait_s)
    replay_started_at = clock()
    for sample in contract.samples:
        deadline = replay_started_at + sample.captured_offset_ms / 1_000 / speed_multiplier
        remaining_s = deadline - clock()
        if remaining_s > 0:
            sleeper(remaining_s)
        runner(_adb_fix_command(prefix, sample))
    return len(contract.samples)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--play", action="store_true", help="생성 뒤 실행 중인 AVD에 ADB 재생")
    parser.add_argument("--speed", type=float, default=1.0, help="ADB 재생 배속")
    parser.add_argument("--adb", default="adb", help="adb 실행 파일")
    parser.add_argument("--serial", help="adb -s에 넘길 emulator serial")
    parser.add_argument(
        "--prime-wait",
        type=float,
        default=0.0,
        help="첫 좌표를 미리 주입한 뒤 산책 시작 버튼을 누를 대기 시간(초)",
    )
    parser.add_argument(
        "--allow-unapplied-controls",
        action="store_true",
        help="chain pause/resume을 적용하지 못한 채 좌표만 재생하는 것을 명시적으로 허용",
    )
    args = parser.parse_args(argv)
    try:
        spec = WalkTraceScenarioSpec.model_validate_json(args.spec.read_text(encoding="utf-8"))
        scenario = build_scenario_from_spec(spec)
        artifacts = build_android_replay_artifacts(scenario)
        if args.play:
            # 사용자 입력 오류는 출력 폴더를 만들기 전에 끊어 같은 경로로 재시도할 수 있게 한다.
            _validate_adb_replay(
                artifacts.replay,
                speed_multiplier=args.speed,
                prime_wait_s=args.prime_wait,
                allow_unapplied_controls=args.allow_unapplied_controls,
            )
        write_android_replay(args.out.resolve(), artifacts)
        played = 0
        if args.play:
            played = replay_with_adb(
                artifacts.replay,
                speed_multiplier=args.speed,
                adb_binary=args.adb,
                serial=args.serial,
                prime_wait_s=args.prime_wait,
                allow_unapplied_controls=args.allow_unapplied_controls,
            )
    except (
        FileExistsError,
        json.JSONDecodeError,
        OSError,
        subprocess.CalledProcessError,
        ValidationError,
        ValueError,
    ) as error:
        parser.error(str(error))

    print(
        f"{artifacts.replay.scenario_id} · capture {len(artifacts.replay.samples)} fixes · "
        f"missing {artifacts.replay.receipt.omitted_missing_sample_count} · "
        f"controls {len(artifacts.replay.control_events)}"
    )
    if played:
        print(f"ADB replayed {played} fixes at {args.speed:g}×")
    print(f"written to {args.out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
