"""파일로 저장하고 다시 실행할 수 있는 산책 trace 시나리오 계약."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scripts.sim.walk.model import BehaviorPlan, HoldEvent, SlowMotif
from scripts.sim.walk.route import RouteGeometry
from scripts.sim.walk.sensor import NoisySensor, PerfectSensor

SCENARIO_FORMAT = "walk-trace-scenario-v1"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class OriginSpec(_StrictModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class RouteSpec(_StrictModel):
    """미터 단위 로컬 east/north polyline. UI가 그린 경로의 저장 형태다."""

    name: str = Field(min_length=1, max_length=64)
    points_xy: tuple[tuple[float, float], ...] = Field(min_length=2)

    @model_validator(mode="after")
    def valid_geometry(self) -> RouteSpec:
        RouteGeometry.from_points(self.name, self.points_xy)
        return self

    def to_geometry(self) -> RouteGeometry:
        return RouteGeometry.from_points(self.name, self.points_xy)


class SlowMotifSpec(_StrictModel):
    centre_m: float = Field(ge=0)
    width_m: float = Field(gt=0)
    min_factor: float = Field(gt=0, le=1)

    def to_model(self) -> SlowMotif:
        return SlowMotif(**self.model_dump())


class HoldSpec(_StrictModel):
    progress_m: float = Field(ge=0)
    duration_s: float = Field(gt=0)

    def to_model(self) -> HoldEvent:
        return HoldEvent(**self.model_dump())


class MotionSpec(_StrictModel):
    """경로와 독립적인 속도·감속·정지 계획. 길이는 route에서 하나만 취한다."""

    name: str = Field(min_length=1, max_length=64)
    base_speed_mps: float = Field(gt=0)
    slow_motifs: tuple[SlowMotifSpec, ...] = ()
    holds: tuple[HoldSpec, ...] = ()
    fatigue_start_fraction: float = Field(0.6, ge=0, lt=1)
    fatigue_end_factor: float = Field(1.0, gt=0, le=1)

    def to_behavior(self, length_m: float) -> BehaviorPlan:
        return BehaviorPlan(
            name=self.name,  # type: ignore[arg-type] -- custom scenario labels are intentional.
            length_m=length_m,
            base_speed_mps=self.base_speed_mps,
            slow_motifs=tuple(item.to_model() for item in self.slow_motifs),
            holds=tuple(item.to_model() for item in self.holds),
            fatigue_start_fraction=self.fatigue_start_fraction,
            fatigue_end_factor=self.fatigue_end_factor,
        )


class SensorSpec(_StrictModel):
    """확률적 센서 오염. 시간축의 의도적인 사건은 ``faults``에 둔다."""

    kind: Literal["perfect", "noisy"] = "perfect"
    sample_interval_s: float = Field(5.0, gt=0)
    accuracy_m: float = Field(3.0, ge=0)
    jitter_sigma_m: float = Field(0.0, ge=0)
    accuracy_sigma_m: float = Field(0.0, ge=0)
    dropout_rate: float = Field(0.0, ge=0, lt=1)
    outlier_rate: float = Field(0.0, ge=0, lt=1)
    outlier_distance_m: float = Field(260.0, ge=0)
    drift_east_m: float = 0.0
    drift_north_m: float = 0.0
    low_accuracy_rate: float = Field(0.0, ge=0, lt=1)
    low_accuracy_m: float = Field(80.0, ge=0)
    chain_breaks_m: tuple[float, ...] = ()

    @model_validator(mode="after")
    def valid_sensor(self) -> SensorSpec:
        if self.kind == "perfect" and any(
            value != 0
            for value in (
                self.jitter_sigma_m,
                self.accuracy_sigma_m,
                self.dropout_rate,
                self.outlier_rate,
                self.drift_east_m,
                self.drift_north_m,
                self.low_accuracy_rate,
            )
        ):
            raise ValueError("perfect sensor cannot define stochastic noise")
        self.to_sensor(seed=0)
        return self

    def to_sensor(self, *, seed: int) -> PerfectSensor | NoisySensor:
        shared = {
            "sample_interval_s": self.sample_interval_s,
            "accuracy_m": self.accuracy_m,
            "chain_breaks_m": self.chain_breaks_m,
        }
        if self.kind == "perfect":
            return PerfectSensor(**shared)
        return NoisySensor(
            **shared,
            jitter_sigma_m=self.jitter_sigma_m,
            accuracy_sigma_m=self.accuracy_sigma_m,
            dropout_rate=self.dropout_rate,
            outlier_rate=self.outlier_rate,
            outlier_distance_m=self.outlier_distance_m,
            drift_east_m=self.drift_east_m,
            drift_north_m=self.drift_north_m,
            low_accuracy_rate=self.low_accuracy_rate,
            low_accuracy_m=self.low_accuracy_m,
            seed=seed,
        )


class DropoutFault(_StrictModel):
    kind: Literal["dropout"] = "dropout"
    id: str = Field(min_length=1, max_length=64)
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self) -> DropoutFault:
        if self.end_s < self.start_s:
            raise ValueError("fault end_s must not precede start_s")
        return self


class PositionOffsetFault(_StrictModel):
    kind: Literal["position_offset"] = "position_offset"
    id: str = Field(min_length=1, max_length=64)
    at_s: float = Field(ge=0)
    east_m: float = 0.0
    north_m: float = 0.0

    @model_validator(mode="after")
    def non_zero_offset(self) -> PositionOffsetFault:
        if self.east_m == 0 and self.north_m == 0:
            raise ValueError("position offset must move at least one axis")
        return self


class AccuracyFault(_StrictModel):
    kind: Literal["accuracy"] = "accuracy"
    id: str = Field(min_length=1, max_length=64)
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    accuracy_m: float = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self) -> AccuracyFault:
        if self.end_s < self.start_s:
            raise ValueError("fault end_s must not precede start_s")
        return self


SensorFault = Annotated[
    DropoutFault | PositionOffsetFault | AccuracyFault,
    Field(discriminator="kind"),
]


class DeliveryDelaySpec(_StrictModel):
    id: str = Field(min_length=1, max_length=64)
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    delay_s: float = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> DeliveryDelaySpec:
        if self.end_s < self.start_s:
            raise ValueError("delivery delay end_s must not precede start_s")
        return self


class DeliverySpec(_StrictModel):
    """센서가 캡처한 뒤 앱에 도착하는 지연·배치·중복 순서."""

    base_latency_s: float = Field(0.0, ge=0)
    batch_size: int = Field(1, ge=1, le=10_000)
    reverse_within_batch: bool = False
    delay_windows: tuple[DeliveryDelaySpec, ...] = ()
    duplicate_at_s: tuple[float, ...] = ()

    @field_validator("duplicate_at_s")
    @classmethod
    def duplicates_are_ordered(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if any(not math.isfinite(item) or item < 0 for item in value):
            raise ValueError("duplicate_at_s values must be finite and non-negative")
        if tuple(sorted(set(value))) != value:
            raise ValueError("duplicate_at_s values must be unique and ordered")
        return value


class WalkTraceScenarioSpec(_StrictModel):
    format: Literal[SCENARIO_FORMAT] = SCENARIO_FORMAT
    seed: int = 0
    session_id: str | None = Field(None, min_length=1, max_length=128)
    dog_id: str = Field("simulated-dog", min_length=1, max_length=128)
    started_at: datetime
    origin: OriginSpec
    route: RouteSpec
    motion: MotionSpec
    sensor: SensorSpec = SensorSpec()
    faults: tuple[SensorFault, ...] = ()
    delivery: DeliverySpec = DeliverySpec()

    @field_validator("started_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("started_at must include a timezone")
        return value

    @model_validator(mode="after")
    def event_ids_are_unique(self) -> WalkTraceScenarioSpec:
        event_ids = [fault.id for fault in self.faults]
        event_ids.extend(window.id for window in self.delivery.delay_windows)
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("fault and delivery event ids must be unique")
        return self
