"""truth, GPS observation, delivery를 같은 sample id로 묶는 evaluator trace."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.features.walk.models import WalkFix
from app.geo.cells import EARTH_R
from scripts.sim.walk.kinematics import MotionTruth
from scripts.sim.walk.sensor import ObservedWalk
from scripts.sim.walk.spec import (
    AccuracyFault,
    DeliverySpec,
    DropoutFault,
    SensorFault,
)


def _elapsed_s(walk: ObservedWalk, fix: WalkFix) -> float:
    return (fix.at - walk.started_at).total_seconds()


def _sample_key(elapsed_s: float) -> int:
    return round(elapsed_s * 1_000_000)


def _sample_id(index: int) -> str:
    return f"sample-{index:06d}"


def _offset_fix(fix: WalkFix, east_m: float, north_m: float) -> WalkFix:
    lat = fix.lat + math.degrees(north_m / EARTH_R)
    longitude_radius = EARTH_R * math.cos(math.radians(fix.lat))
    lng = fix.lng + math.degrees(east_m / longitude_radius)
    return WalkFix.model_validate(fix.model_dump() | {"lat": round(lat, 9), "lng": round(lng, 9)})


def apply_sensor_faults(
    walk: ObservedWalk,
    faults: tuple[SensorFault, ...],
    *,
    motion: MotionTruth,
    sample_interval_s: float,
) -> ObservedWalk:
    """확률 센서 결과 위에 사람이 지정한 시간축 결함을 순서대로 적용한다."""
    fixes = list(walk.fixes)
    truth_samples = motion.samples(sample_interval_s)
    for fault in faults:
        if isinstance(fault, (DropoutFault, AccuracyFault)):
            if fault.end_s > motion.duration_s:
                raise ValueError(f"fault {fault.id!r} exceeds motion duration")
        elif fault.at_s > motion.duration_s:
            raise ValueError(f"fault {fault.id!r} exceeds motion duration")

        if isinstance(fault, DropoutFault):
            fixes = [
                fix for fix in fixes if not fault.start_s <= _elapsed_s(walk, fix) <= fault.end_s
            ]
        elif isinstance(fault, AccuracyFault):
            fixes = [
                fix.model_copy(update={"accuracy_m": fault.accuracy_m})
                if fault.start_s <= _elapsed_s(walk, fix) <= fault.end_s
                else fix
                for fix in fixes
            ]
        elif fixes:
            target = min(
                truth_samples,
                key=lambda sample: abs(sample.elapsed_s - fault.at_s),
            )
            target_key = _sample_key(target.elapsed_s)
            for index, fix in enumerate(fixes):
                if _sample_key(_elapsed_s(walk, fix)) == target_key:
                    fixes[index] = _offset_fix(fix, fault.east_m, fault.north_m)
                    break

    if len(fixes) < 2:
        raise ValueError("sensor faults must leave at least two observed fixes")
    fixes = [
        WalkFix.model_validate(fix.model_dump() | {"client_seq": index})
        for index, fix in enumerate(fixes)
    ]
    return ObservedWalk(
        session_id=walk.session_id,
        dog_id=walk.dog_id,
        started_at=walk.started_at,
        ended_at=fixes[-1].at,
        fixes=tuple(fixes),
    )


def build_trace(
    motion: MotionTruth,
    observed: ObservedWalk,
    *,
    sample_interval_s: float,
    faults: tuple[SensorFault, ...],
) -> dict[str, object]:
    truth_samples = motion.samples(sample_interval_s)
    sample_ids = {
        _sample_key(sample.elapsed_s): _sample_id(index)
        for index, sample in enumerate(truth_samples)
    }
    fixes = {_sample_key(_elapsed_s(observed, fix)): fix for fix in observed.fixes}
    rows = []
    for index, sample in enumerate(truth_samples):
        active_faults = []
        for fault in faults:
            if isinstance(fault, (DropoutFault, AccuracyFault)):
                active = fault.start_s <= sample.elapsed_s <= fault.end_s
            else:
                nearest = min(
                    truth_samples,
                    key=lambda item: abs(item.elapsed_s - fault.at_s),
                )
                active = sample is nearest
            if active:
                active_faults.append(fault.id)
        fix = fixes.get(_sample_key(sample.elapsed_s))
        rows.append(
            {
                "sample_id": _sample_id(index),
                "captured_elapsed_s": round(sample.elapsed_s, 6),
                "truth": sample.to_dict(),
                "observed_fix": fix.model_dump(mode="json") if fix else None,
                "fault_ids": active_faults,
            }
        )
    return {
        "format": "walk-trace-v1",
        "session_id": observed.session_id,
        "sample_interval_s": sample_interval_s,
        "samples": rows,
        "observed_sample_ids": [
            sample_ids[_sample_key(_elapsed_s(observed, fix))] for fix in observed.fixes
        ],
    }


@dataclass(frozen=True)
class _ScheduledFix:
    sample_id: str
    fix: WalkFix
    captured_s: float
    planned_delivery_s: float


def build_delivery(
    motion: MotionTruth,
    observed: ObservedWalk,
    spec: DeliverySpec,
    *,
    sample_interval_s: float,
) -> dict[str, object]:
    """수집 순서와 별개인 앱 도착 순서를 계산한다. walk-export 자체는 바꾸지 않는다."""
    for window in spec.delay_windows:
        if window.end_s > motion.duration_s:
            raise ValueError(f"delivery delay {window.id!r} exceeds motion duration")
    if any(target_s > motion.duration_s for target_s in spec.duplicate_at_s):
        raise ValueError("duplicate_at_s exceeds motion duration")
    truth_samples = motion.samples(sample_interval_s)
    sample_ids = {
        _sample_key(sample.elapsed_s): _sample_id(index)
        for index, sample in enumerate(truth_samples)
    }
    scheduled = []
    for fix in observed.fixes:
        captured_s = _elapsed_s(observed, fix)
        delay_s = math.fsum(
            window.delay_s
            for window in spec.delay_windows
            if window.start_s <= captured_s <= window.end_s
        )
        scheduled.append(
            _ScheduledFix(
                sample_id=sample_ids[_sample_key(captured_s)],
                fix=fix,
                captured_s=captured_s,
                planned_delivery_s=captured_s + spec.base_latency_s + delay_s,
            )
        )

    batches: list[list[_ScheduledFix]] = [
        scheduled[index : index + spec.batch_size]
        for index in range(0, len(scheduled), spec.batch_size)
    ]
    duplicate_ids = {
        _sample_id(
            min(
                range(len(truth_samples)),
                key=lambda index: abs(truth_samples[index].elapsed_s - target_s),
            )
        )
        for target_s in spec.duplicate_at_s
    }
    unordered = []
    for batch_index, batch in enumerate(batches):
        release_s = max(item.planned_delivery_s for item in batch)
        ordered = list(reversed(batch)) if spec.reverse_within_batch else batch
        for within_batch, item in enumerate(ordered):
            unordered.append((release_s, batch_index, within_batch, False, item))
            if item.sample_id in duplicate_ids:
                unordered.append((release_s, batch_index, within_batch, True, item))
    unordered.sort(key=lambda row: (row[0], row[1], row[2], row[3]))

    events = []
    for delivery_index, (release_s, batch_index, _, duplicate, item) in enumerate(unordered):
        events.append(
            {
                "delivery_id": f"delivery-{delivery_index:06d}",
                "delivery_index": delivery_index,
                "batch_id": f"batch-{batch_index:06d}",
                "sample_id": item.sample_id,
                "client_seq": item.fix.client_seq,
                "captured_elapsed_s": round(item.captured_s, 6),
                "delivered_elapsed_s": round(release_s, 6),
                "duplicate": duplicate,
            }
        )
    return {
        "format": "walk-delivery-v1",
        "session_id": observed.session_id,
        "events": events,
    }
