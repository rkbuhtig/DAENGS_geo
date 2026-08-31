"""지도와 GPS보다 앞선 1차원 행동 계약.

속도·정지를 먼저 만들고 짙기는 만들지 않는다. Cellophane occupancy는 이 행동을 실제 경로와
관측기로 통과시킨 뒤 기존 Paint가 계산할 결과다. 생성기 내부 상태도 제품 판정의 정답이
아니다. 관측을 잃거나 흔들었을 때 현재 판정기가 무엇을 회수하는지 재기 위한 독립 truth다.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Literal

GENERATOR_VERSION = 1
BehaviorName = Literal["steady", "exploratory", "fatigued", "stop-heavy"]


def _finite_positive(value: float, name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


@dataclass(frozen=True)
class SlowMotif:
    """거리축 위의 부드러운 감속 하나. `min_factor`는 중심에서의 기준속도 비율이다."""

    centre_m: float
    width_m: float
    min_factor: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.centre_m) or self.centre_m < 0:
            raise ValueError("centre_m must be finite and non-negative")
        _finite_positive(self.width_m, "width_m")
        if not math.isfinite(self.min_factor) or not 0 < self.min_factor <= 1:
            raise ValueError("min_factor must be in (0, 1]")

    @property
    def start_m(self) -> float:
        return self.centre_m - self.width_m / 2

    @property
    def end_m(self) -> float:
        return self.centre_m + self.width_m / 2

    def factor_at(self, progress_m: float) -> float:
        if progress_m <= self.start_m or progress_m >= self.end_m:
            return 1.0
        phase = (progress_m - self.start_m) / self.width_m
        bump = math.sin(math.pi * phase) ** 2
        return 1.0 - (1.0 - self.min_factor) * bump

    def to_dict(self) -> dict[str, float]:
        return {
            "centre_m": round(self.centre_m, 3),
            "width_m": round(self.width_m, 3),
            "min_factor": round(self.min_factor, 4),
        }


@dataclass(frozen=True)
class HoldEvent:
    """진행거리 한 점에 추가되는 정지 시간 질량."""

    progress_m: float
    duration_s: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.progress_m) or self.progress_m < 0:
            raise ValueError("progress_m must be finite and non-negative")
        _finite_positive(self.duration_s, "duration_s")

    def to_dict(self) -> dict[str, float]:
        return {
            "progress_m": round(self.progress_m, 3),
            "duration_s": round(self.duration_s, 3),
        }


@dataclass(frozen=True)
class BehaviorPlan:
    """지도 독립적인 산책 테이프. 속도장은 연속이고 완전 정지는 별도 사건이다."""

    name: BehaviorName
    length_m: float
    base_speed_mps: float
    slow_motifs: tuple[SlowMotif, ...] = ()
    holds: tuple[HoldEvent, ...] = ()
    fatigue_start_fraction: float = 0.6
    fatigue_end_factor: float = 1.0

    def __post_init__(self) -> None:
        _finite_positive(self.length_m, "length_m")
        _finite_positive(self.base_speed_mps, "base_speed_mps")
        if not 0 <= self.fatigue_start_fraction < 1:
            raise ValueError("fatigue_start_fraction must be in [0, 1)")
        if not math.isfinite(self.fatigue_end_factor) or not 0 < self.fatigue_end_factor <= 1:
            raise ValueError("fatigue_end_factor must be in (0, 1]")
        if any(motif.end_m > self.length_m for motif in self.slow_motifs):
            raise ValueError("slow motif must fit inside behavior length")
        if any(hold.progress_m > self.length_m for hold in self.holds):
            raise ValueError("hold must fit inside behavior length")
        if tuple(sorted(self.holds, key=lambda event: event.progress_m)) != self.holds:
            raise ValueError("holds must be ordered by progress_m")

    def fatigue_factor_at(self, progress_m: float) -> float:
        start_m = self.length_m * self.fatigue_start_fraction
        if progress_m <= start_m:
            return 1.0
        ratio = min(1.0, (progress_m - start_m) / (self.length_m - start_m))
        return 1.0 + ratio * (self.fatigue_end_factor - 1.0)

    def speed_at(self, progress_m: float) -> float:
        if not 0 <= progress_m <= self.length_m:
            raise ValueError("progress_m is outside behavior length")
        motif_factor = math.prod(motif.factor_at(progress_m) for motif in self.slow_motifs)
        return self.base_speed_mps * self.fatigue_factor_at(progress_m) * motif_factor

    def state_at(self, progress_m: float) -> str:
        if any(motif.factor_at(progress_m) < 0.999999 for motif in self.slow_motifs):
            return "slow"
        if self.fatigue_factor_at(progress_m) < 0.999999:
            return "fatigue"
        return "cruise"

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "length_m": self.length_m,
            "base_speed_mps": self.base_speed_mps,
            "fatigue_start_fraction": self.fatigue_start_fraction,
            "fatigue_end_factor": self.fatigue_end_factor,
            "slow_motifs": [motif.to_dict() for motif in self.slow_motifs],
            "holds": [hold.to_dict() for hold in self.holds],
        }


def _clamp_centre(value: float, width: float, length_m: float) -> float:
    return min(length_m - width / 2, max(width / 2, value))


def behavior_preset(name: BehaviorName, length_m: float, seed: int) -> BehaviorPlan:
    """명시적인 motif 조리법에 seed 기반의 제한된 변형만 준다.

    아직 실제 기기 분포로 보정하지 않았으므로 Poisson/HMM 같은 그럴듯한 확률 모델을
    주장하지 않는다. manifest에 최종 motif를 전부 남겨 같은 입력을 재생할 수 있다.
    """
    _finite_positive(length_m, "length_m")
    if length_m < 120:
        raise ValueError("length_m must be at least 120m for behavior presets")
    rng = random.Random(seed)

    def motif(fraction: float, width_fraction: float, factor: float) -> SlowMotif:
        width = max(12.0, length_m * width_fraction * rng.uniform(0.85, 1.15))
        centre = length_m * fraction + rng.uniform(-0.025, 0.025) * length_m
        return SlowMotif(
            centre_m=_clamp_centre(centre, width, length_m),
            width_m=width,
            min_factor=max(0.08, factor * rng.uniform(0.9, 1.1)),
        )

    if name == "steady":
        return BehaviorPlan(name, length_m, 1.28 + rng.uniform(-0.04, 0.04))
    if name == "exploratory":
        motifs = tuple(sorted((
            motif(0.20, 0.055, 0.48),
            motif(0.43, 0.035, 0.22),
            motif(0.70, 0.070, 0.55),
            motif(0.86, 0.030, 0.30),
        ), key=lambda item: item.centre_m))
        holds = tuple(sorted((
            HoldEvent(length_m * 0.34, rng.uniform(16.0, 28.0)),
            HoldEvent(length_m * 0.78, rng.uniform(28.0, 44.0)),
        ), key=lambda item: item.progress_m))
        return BehaviorPlan(name, length_m, 1.30, motifs, holds)
    if name == "fatigued":
        motifs = (motif(0.35, 0.05, 0.58), motif(0.73, 0.06, 0.46))
        return BehaviorPlan(
            name, length_m, 1.34, motifs, (),
            fatigue_start_fraction=0.45, fatigue_end_factor=0.64,
        )
    if name == "stop-heavy":
        motifs = (motif(0.30, 0.05, 0.25), motif(0.62, 0.05, 0.30))
        holds = tuple(
            HoldEvent(length_m * fraction, rng.uniform(low, high))
            for fraction, low, high in ((0.18, 12, 20), (0.47, 25, 42), (0.82, 18, 32))
        )
        return BehaviorPlan(name, length_m, 1.22, motifs, holds)
    raise ValueError(f"unknown behavior preset: {name}")
