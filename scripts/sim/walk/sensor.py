"""실제 동선을 제품 `WalkFix` 관측열로 바꾸는 경계.

첫 버전은 의도적으로 perfect sensor만 둔다. GPS drift·dropout·outlier는 truth와 canonical
연결을 먼저 고정한 다음 별도 버전으로 추가한다. 명시적 pause/resume chain만 관측 계약으로
지원한다.
"""

from __future__ import annotations

import math
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
