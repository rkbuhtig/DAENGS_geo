"""latent 모집단을 observed GPS → canonical Segment → Cellophane으로 통과시킨다.

반환값에는 `branch`, route 선택, 심은 hold 같은 latent truth가 없다. 통계 계산기는 오직
`PopulationObservation.sheets`를 받고, 평가는 별도로 보관한 `PopulationTruth`와 사후 비교한다.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from app.features.territory.paint import NARROW_STEP, Cellophane, paint_sheet
from app.features.walk.facts import ComputedFacts, compute_facts
from scripts.sim.walk.kinematics import integrate_motion
from scripts.sim.walk.population_truth import PopulationTruth
from scripts.sim.walk.sensor import ObservedWalk, PerfectSensor, observe_perfectly

DEFAULT_POPULATION_ORIGIN = (37.4979, 127.0276)


@dataclass(frozen=True)
class PopulationWalkObservation:
    """제품이 받을 수 있는 한 산책의 관측·canonical·공간장."""

    observed: ObservedWalk
    computed: ComputedFacts
    sheet: Cellophane

    def __post_init__(self) -> None:
        identities = {
            self.observed.session_id,
            self.computed.facts.session_id,
            self.sheet.walk_id,
        }
        if len(identities) != 1:
            raise ValueError("observed, computed, Cellophane walk identity must match")

    @property
    def accepted_segment_s(self) -> float:
        return math.fsum(segment.dt for segment in self.computed.segments)


@dataclass(frozen=True)
class PopulationObservation:
    """latent label을 제거한 30개의 독립 Cellophane z축."""

    generator_version: int
    run_id: str
    walks: tuple[PopulationWalkObservation, ...]

    @property
    def sheets(self) -> tuple[Cellophane, ...]:
        return tuple(walk.sheet for walk in self.walks)


def observe_population(
    truth: PopulationTruth,
    *,
    sample_interval_s: float = 5.0,
    radius_u: float = 8.0,
    origin_lat: float = DEFAULT_POPULATION_ORIGIN[0],
    origin_lng: float = DEFAULT_POPULATION_ORIGIN[1],
) -> PopulationObservation:
    """truth를 생성 입력으로만 사용하고 결과에서는 evaluator-only label을 제거한다."""
    sensor = PerfectSensor(sample_interval_s=sample_interval_s, accuracy_m=3.0)
    signature = (
        f"{truth.generator_version}|{truth.seed}|{sample_interval_s}|{radius_u}|"
        f"{origin_lat}|{origin_lng}"
    )
    run_id = hashlib.sha256(signature.encode()).hexdigest()[:12]
    walks = []
    for planted in truth.walks:
        session_id = f"cellophane-pop-v{truth.generator_version}-{run_id}-{planted.walk_id}"
        motion = integrate_motion(planted.behavior, planted.route)
        observed = observe_perfectly(
            motion,
            sensor,
            session_id=session_id,
            dog_id="simulated-population-dog",
            started_at=planted.started_at,
            origin_lat=origin_lat,
            origin_lng=origin_lng,
        )
        computed = compute_facts(
            session_id,
            observed.dog_id,
            observed.started_at,
            observed.ended_at,
            list(observed.fixes),
        )
        sheet = paint_sheet(
            session_id, observed.started_at, computed.segments, radius_u, NARROW_STEP
        )
        walks.append(PopulationWalkObservation(observed, computed, sheet))
    return PopulationObservation(truth.generator_version, run_id, tuple(walks))
