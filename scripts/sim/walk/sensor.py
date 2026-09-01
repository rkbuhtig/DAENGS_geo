"""실제 동선을 제품 `WalkFix` 관측열로 바꾸는 경계.

`PerfectSensor`는 기준 관측을, `NoisySensor`는 evaluator-only GPS 오염을 만든다. 오염은
동일한 motion sample마다 seed와 session identity로 결정되므로 반복 실행에서 재현된다. 제품
수집기나 canonical 필터 정책을 흉내 내지 않고 그 입력인 `WalkFix`만 변형한다.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.features.walk.models import WalkFix
from app.geo.cells import EARTH_R
from scripts.sim.walk.kinematics import MotionTruth


@dataclass(frozen=True)
class PerfectSensor:
    sample_interval_s: float = 5.0
    accuracy_m: float = 3.0
    chain_breaks_m: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not math.isfinite(self.sample_interval_s) or self.sample_interval_s <= 0:
            raise ValueError("sample_interval_s must be finite and positive")
        if not math.isfinite(self.accuracy_m) or self.accuracy_m < 0:
            raise ValueError("accuracy_m must be finite and non-negative")
        if tuple(sorted(set(self.chain_breaks_m))) != self.chain_breaks_m:
            raise ValueError("chain_breaks_m must be unique and ordered")
        if any(not math.isfinite(value) or value <= 0 for value in self.chain_breaks_m):
            raise ValueError("chain breaks must be finite and positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "perfect",
            "sample_interval_s": self.sample_interval_s,
            "accuracy_m": self.accuracy_m,
            "chain_breaks_m": list(self.chain_breaks_m),
        }


@dataclass(frozen=True)
class NoisySensor:
    """실기기 실패 양상을 분리해 주입하는 evaluator-only 센서."""

    sample_interval_s: float = 5.0
    accuracy_m: float = 3.0
    jitter_sigma_m: float = 0.0
    accuracy_sigma_m: float = 0.0
    dropout_rate: float = 0.0
    outlier_rate: float = 0.0
    outlier_distance_m: float = 260.0
    drift_east_m: float = 0.0
    drift_north_m: float = 0.0
    low_accuracy_rate: float = 0.0
    low_accuracy_m: float = 80.0
    chain_breaks_m: tuple[float, ...] = ()
    seed: int = 0

    def __post_init__(self) -> None:
        PerfectSensor(
            sample_interval_s=self.sample_interval_s,
            accuracy_m=self.accuracy_m,
            chain_breaks_m=self.chain_breaks_m,
        )
        for name, value in (
            ("jitter_sigma_m", self.jitter_sigma_m),
            ("accuracy_sigma_m", self.accuracy_sigma_m),
            ("outlier_distance_m", self.outlier_distance_m),
            ("low_accuracy_m", self.low_accuracy_m),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        for name, value in (
            ("dropout_rate", self.dropout_rate),
            ("outlier_rate", self.outlier_rate),
            ("low_accuracy_rate", self.low_accuracy_rate),
        ):
            if not math.isfinite(value) or not 0 <= value < 1:
                raise ValueError(f"{name} must be finite and in [0, 1)")
        for name, value in (
            ("drift_east_m", self.drift_east_m),
            ("drift_north_m", self.drift_north_m),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.outlier_rate > 0 and self.outlier_distance_m <= 0:
            raise ValueError("positive outlier_rate requires outlier_distance_m > 0")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "noisy",
            "sample_interval_s": self.sample_interval_s,
            "accuracy_m": self.accuracy_m,
            "jitter_sigma_m": self.jitter_sigma_m,
            "accuracy_sigma_m": self.accuracy_sigma_m,
            "dropout_rate": self.dropout_rate,
            "outlier_rate": self.outlier_rate,
            "outlier_distance_m": self.outlier_distance_m,
            "drift_east_m": self.drift_east_m,
            "drift_north_m": self.drift_north_m,
            "low_accuracy_rate": self.low_accuracy_rate,
            "low_accuracy_m": self.low_accuracy_m,
            "chain_breaks_m": list(self.chain_breaks_m),
            "seed": self.seed,
        }


@dataclass(frozen=True)
class ObservedWalk:
    session_id: str
    dog_id: str
    started_at: datetime
    ended_at: datetime
    fixes: tuple[WalkFix, ...]

    def to_export(self) -> dict[str, object]:
        return {
            "format": 1,
            "session": {
                "id": self.session_id,
                "dog_id": self.dog_id,
                "started_at": self.started_at.isoformat(),
                "ended_at": self.ended_at.isoformat(),
            },
            "fixes": [fix.model_dump(mode="json") for fix in self.fixes],
        }


def local_xy_to_latlng(
    east_m: float, north_m: float, origin_lat: float, origin_lng: float
) -> tuple[float, float]:
    lat = origin_lat + math.degrees(north_m / EARTH_R)
    lng = origin_lng + math.degrees(east_m / (EARTH_R * math.cos(math.radians(origin_lat))))
    return lat, lng


def observe_perfectly(
    truth: MotionTruth,
    sensor: PerfectSensor,
    *,
    session_id: str,
    dog_id: str,
    started_at: datetime,
    origin_lat: float,
    origin_lng: float,
) -> ObservedWalk:
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise ValueError("started_at must include a timezone")
    if not -90 <= origin_lat <= 90 or not -180 <= origin_lng <= 180:
        raise ValueError("origin is outside latitude/longitude bounds")
    if any(value >= truth.behavior.length_m for value in sensor.chain_breaks_m):
        raise ValueError("chain break must be inside motion length")

    fixes = []
    for sample in truth.samples(sensor.sample_interval_s):
        # break 지점 자체는 이전 chain의 마지막 점이다. 그보다 전진한 첫 fix부터 새 chain이다.
        chain_index = sum(sample.progress_m > value for value in sensor.chain_breaks_m)
        lat, lng = local_xy_to_latlng(sample.east_m, sample.north_m, origin_lat, origin_lng)
        fixes.append(
            WalkFix(
                client_seq=len(fixes),
                chain_index=chain_index,
                at=started_at + timedelta(seconds=sample.elapsed_s),
                lat=round(lat, 9),
                lng=round(lng, 9),
                accuracy_m=sensor.accuracy_m,
                is_mock=True,
            )
        )
    return ObservedWalk(
        session_id=session_id,
        dog_id=dog_id,
        started_at=started_at,
        ended_at=fixes[-1].at,
        fixes=tuple(fixes),
    )


def _axis_rng(
    sensor: NoisySensor,
    noise_key: str,
    sample_index: int,
    axis: str,
) -> random.Random:
    """profile 강도와 무관한 common-random-number stream을 현상별로 만든다."""
    encoded = f"{sensor.seed}:{noise_key}:{sample_index}:{axis}".encode()
    return random.Random(int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big"))


def observe_noisily(
    truth: MotionTruth,
    sensor: NoisySensor,
    *,
    session_id: str,
    dog_id: str,
    started_at: datetime,
    origin_lat: float,
    origin_lng: float,
    noise_key: str | None = None,
) -> ObservedWalk:
    """motion truth를 결정론적 dropout·jitter·outlier·drift·accuracy 오염으로 관측한다."""
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise ValueError("started_at must include a timezone")
    if not -90 <= origin_lat <= 90 or not -180 <= origin_lng <= 180:
        raise ValueError("origin is outside latitude/longitude bounds")
    if any(value >= truth.behavior.length_m for value in sensor.chain_breaks_m):
        raise ValueError("chain break must be inside motion length")

    stable_noise_key = session_id if noise_key is None else noise_key
    if not stable_noise_key:
        raise ValueError("noise_key must not be empty")
    samples = tuple(truth.samples(sensor.sample_interval_s))
    fixes = []
    for sample_index, sample in enumerate(samples):
        endpoint = sample_index in {0, len(samples) - 1}
        if (
            not endpoint
            and _axis_rng(sensor, stable_noise_key, sample_index, "dropout").random()
            < sensor.dropout_rate
        ):
            continue

        duration_fraction = sample.elapsed_s / truth.duration_s if truth.duration_s else 0.0
        east_m = sample.east_m + sensor.drift_east_m * duration_fraction
        north_m = sample.north_m + sensor.drift_north_m * duration_fraction
        if sensor.jitter_sigma_m:
            jitter_rng = _axis_rng(sensor, stable_noise_key, sample_index, "jitter")
            east_m += jitter_rng.gauss(0.0, sensor.jitter_sigma_m)
            north_m += jitter_rng.gauss(0.0, sensor.jitter_sigma_m)
        outlier_rng = _axis_rng(sensor, stable_noise_key, sample_index, "outlier")
        if not endpoint and outlier_rng.random() < sensor.outlier_rate:
            angle = outlier_rng.uniform(0.0, math.tau)
            east_m += math.cos(angle) * sensor.outlier_distance_m
            north_m += math.sin(angle) * sensor.outlier_distance_m

        accuracy_rng = _axis_rng(sensor, stable_noise_key, sample_index, "accuracy_noise")
        accuracy_m = max(
            0.0,
            sensor.accuracy_m + accuracy_rng.gauss(0.0, sensor.accuracy_sigma_m),
        )
        low_accuracy_rng = _axis_rng(sensor, stable_noise_key, sample_index, "low_accuracy")
        if not endpoint and low_accuracy_rng.random() < sensor.low_accuracy_rate:
            accuracy_m = sensor.low_accuracy_m
        chain_index = sum(sample.progress_m > value for value in sensor.chain_breaks_m)
        lat, lng = local_xy_to_latlng(east_m, north_m, origin_lat, origin_lng)
        fixes.append(
            WalkFix(
                client_seq=len(fixes),
                chain_index=chain_index,
                at=started_at + timedelta(seconds=sample.elapsed_s),
                lat=round(lat, 9),
                lng=round(lng, 9),
                accuracy_m=round(accuracy_m, 3),
                is_mock=True,
            )
        )
    return ObservedWalk(
        session_id=session_id,
        dog_id=dog_id,
        started_at=started_at,
        ended_at=fixes[-1].at,
        fixes=tuple(fixes),
    )
