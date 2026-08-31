"""육각 격자 없이 canonical Segment를 연속 원 브러시 field로 읽는 기준 모델.

제품 저장 형식이나 새 통계 원판이 아니다. 같은 산책을 Hex Cellophane과 비교하기 위한
grid-free reference다. 유효 Segment를 일정한 공간 간격의 시간 질량 원(`BrushDab`)으로
바꾸고, 각 원은 정규화된 `BrushProfile` kernel을 연속 공간에 남긴다.

    canonical Segment
    → dt를 보존하는 BrushDab 열
    → F(x): 임의 위치 x의 관측 시간 밀도(s/m²)

원 하나의 kernel 적분은 1이고 dab의 적분은 `mass_s`다. 따라서 field 전체 적분은 입력
Segment 시간 합과 같다. 서로 다른 continuity chain 사이는 입력에 Segment가 없으므로 새로
연결하지 않는다. GPS accuracy는 위치 불확실성이지 붓 물성이 아니므로 이 모델의 입력이 아니다.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.features.walk.facts import Segment

if TYPE_CHECKING:
    from app.features.territory.paint import BrushProfile

CONTINUOUS_BRUSH_VERSION = 1
EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class ContinuousBrushSpec:
    """연속 reference field를 재현하는 계산 조건."""

    brush_version: int
    profile_name: str
    profile_fp: str
    sample_step_m: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_step_m", float(self.sample_step_m))
        if self.brush_version < 1:
            raise ValueError("brush_version은 양수여야 한다")
        if not self.profile_name or not self.profile_fp:
            raise ValueError("profile identity는 비어 있을 수 없다")
        if not math.isfinite(self.sample_step_m) or self.sample_step_m <= 0:
            raise ValueError("sample_step_m은 유한한 양수여야 한다")

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(
            {
                "brush_version": self.brush_version,
                "profile_fp": self.profile_fp,
                "sample_step_m": self.sample_step_m,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:12]


@dataclass(frozen=True)
class BrushDab:
    """경로 위 한 위치에 놓인, 적분값이 `mass_s`인 원형 시간 질량."""

    lat: float
    lng: float
    mass_s: float
    chain_index: int

    def __post_init__(self) -> None:
        if not math.isfinite(self.lat) or not -90 <= self.lat <= 90:
            raise ValueError("dab latitude는 -90..90의 유한한 값이어야 한다")
        if not math.isfinite(self.lng) or not -180 <= self.lng <= 180:
            raise ValueError("dab longitude는 -180..180의 유한한 값이어야 한다")
        if not math.isfinite(self.mass_s) or self.mass_s <= 0:
            raise ValueError("dab mass_s는 유한한 양수여야 한다")
        if self.chain_index < 0:
            raise ValueError("chain_index는 0 이상이어야 한다")


@dataclass(frozen=True)
class ContinuousBrushField:
    """임의 위치에서 조회할 수 있는 한 산책의 연속 시간 질량 field."""

    spec: ContinuousBrushSpec
    profile: BrushProfile
    dabs: tuple[BrushDab, ...]
    source_segment_s: float
    kernel_area_m2: float

    def __post_init__(self) -> None:
        if self.profile.fingerprint != self.spec.profile_fp:
            raise ValueError("profile이 continuous brush spec과 다르다")
        if not math.isfinite(self.source_segment_s) or self.source_segment_s < 0:
            raise ValueError("source_segment_s는 유한한 0 이상이어야 한다")
        if not math.isfinite(self.kernel_area_m2) or self.kernel_area_m2 <= 0:
            raise ValueError("kernel_area_m2는 유한한 양수여야 한다")
        if not math.isclose(self.mass_s, self.source_segment_s, rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError("연속 brush 질량이 source Segment 시간과 다르다")

    @property
    def mass_s(self) -> float:
        """연속 field의 해석적 전체 적분. dab별 질량 합과 같다."""
        return math.fsum(dab.mass_s for dab in self.dabs)

    @property
    def chain_indexes(self) -> frozenset[int]:
        return frozenset(dab.chain_index for dab in self.dabs)

    def density_s_per_m2_at(self, lat: float, lng: float) -> float:
        """위치의 관측 시간 밀도. 겹치는 dab은 선형으로 더해진다."""
        weighted_s = math.fsum(
            dab.mass_s * self.profile.weight_at(_ground_distance_m(lat, lng, dab.lat, dab.lng))
            for dab in self.dabs
        )
        return weighted_s / self.kernel_area_m2

    def peak_at(self, lat: float, lng: float) -> float:
        """시간과 무관한 최대 근접 세기. 겹침 횟수로 부풀리지 않는다."""
        return max(
            (
                self.profile.weight_at(_ground_distance_m(lat, lng, dab.lat, dab.lng))
                for dab in self.dabs
            ),
            default=0.0,
        )


def continuous_brush_spec(
    profile: BrushProfile,
    step_m: float = 0.0,
) -> ContinuousBrushSpec:
    """grid와 무관하게 연속 reference의 공간 표본 간격을 결정한다."""
    if not math.isfinite(step_m) or step_m < 0:
        raise ValueError("step_m은 0 이상의 유한한 값이어야 한다")
    resolved_step = step_m or max(profile.bands[0] / 2.0, 0.5)
    return ContinuousBrushSpec(
        brush_version=CONTINUOUS_BRUSH_VERSION,
        profile_name=profile.name,
        profile_fp=profile.fingerprint,
        sample_step_m=resolved_step,
    )


def radial_kernel_area_m2(profile: BrushProfile) -> float:
    """`2π∫r·weight(r)dr`. 이 값으로 나누면 원형 kernel의 면적 적분이 1이다."""
    previous_radius = 0.0
    previous_weight = profile.weights[0]
    radial_integral = 0.0
    for radius, weight in zip(profile.bands, profile.weights, strict=True):
        if profile.smooth:
            slope = (weight - previous_weight) / (radius - previous_radius)
            intercept = previous_weight - slope * previous_radius
            radial_integral += (
                intercept * (radius**2 - previous_radius**2) / 2.0
                + slope * (radius**3 - previous_radius**3) / 3.0
            )
        else:
            radial_integral += weight * (radius**2 - previous_radius**2) / 2.0
        previous_radius = radius
        previous_weight = weight
    area = 2.0 * math.pi * radial_integral
    if not math.isfinite(area) or area <= 0:
        raise ValueError("BrushProfile kernel area는 유한한 양수여야 한다")
    return area


def continuous_brush_field(
    segments: list[Segment],
    profile: BrushProfile,
    step_m: float = 0.0,
) -> ContinuousBrushField:
    """canonical Segment만 따라 dt 질량 원을 놓아 grid-free reference를 만든다."""
    spec = continuous_brush_spec(profile, step_m)
    dabs = []
    for segment in segments:
        if not math.isfinite(segment.dt) or segment.dt <= 0:
            raise ValueError("Segment dt는 유한한 양수여야 한다")
        if not math.isfinite(segment.dist) or segment.dist < 0:
            raise ValueError("Segment dist는 유한한 0 이상이어야 한다")
        pieces = max(1, math.ceil(segment.dist / spec.sample_step_m))
        share = segment.dt / pieces
        for index in range(pieces):
            fraction = (index + 0.5) / pieces
            dabs.append(
                BrushDab(
                    lat=segment.a.lat + (segment.b.lat - segment.a.lat) * fraction,
                    lng=segment.a.lng + (segment.b.lng - segment.a.lng) * fraction,
                    mass_s=share,
                    chain_index=segment.chain_index,
                )
            )
    source_segment_s = math.fsum(segment.dt for segment in segments)
    return ContinuousBrushField(
        spec=spec,
        profile=profile,
        dabs=tuple(dabs),
        source_segment_s=source_segment_s,
        kernel_area_m2=radial_kernel_area_m2(profile),
    )


def _ground_distance_m(
    lat_a: float,
    lng_a: float,
    lat_b: float,
    lng_b: float,
) -> float:
    lat1, lat2 = math.radians(lat_a), math.radians(lat_b)
    delta_lat = lat2 - lat1
    delta_lng = math.radians(lng_b - lng_a)
    haversine = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, max(0.0, haversine))))
