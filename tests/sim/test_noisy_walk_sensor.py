"""evaluator-only noisy GPS sensor의 재현성과 canonical 경계."""

from datetime import UTC, datetime

import pytest

from app.features.walk.facts import compute_facts
from scripts.sim.walk.kinematics import integrate_motion
from scripts.sim.walk.model import behavior_preset
from scripts.sim.walk.route import route_preset
from scripts.sim.walk.sensor import NoisySensor, PerfectSensor, observe_noisily, observe_perfectly

START = datetime(2026, 9, 1, 9, tzinfo=UTC)
ORIGIN = (37.4979, 127.0276)


def _motion():
    route = route_preset("s-curve", 500.0)
    return integrate_motion(behavior_preset("steady", route.length_m, seed=17), route)


def _observe(sensor: NoisySensor):
    return observe_noisily(
        _motion(),
        sensor,
        session_id="noisy-sensor-test",
        dog_id="dog",
        started_at=START,
        origin_lat=ORIGIN[0],
        origin_lng=ORIGIN[1],
    )


def test_same_noisy_sensor_reproduces_every_fix():
    sensor = NoisySensor(
        jitter_sigma_m=4.0,
        dropout_rate=0.15,
        outlier_rate=0.02,
        drift_east_m=12.0,
        accuracy_sigma_m=2.0,
        low_accuracy_rate=0.05,
        seed=41,
    )

    assert _observe(sensor).to_export() == _observe(sensor).to_export()


def test_dropout_strength_uses_common_random_numbers():
    light = _observe(NoisySensor(dropout_rate=0.10, seed=83))
    heavy = _observe(NoisySensor(dropout_rate=0.20, seed=83))
    perfect_times = {fix.at for fix in _observe(NoisySensor(seed=83)).fixes}
    light_missing = perfect_times - {fix.at for fix in light.fixes}
    heavy_missing = perfect_times - {fix.at for fix in heavy.fixes}

    assert light_missing
    assert light_missing < heavy_missing


def test_enabling_jitter_does_not_resample_other_failure_axes():
    shared = {
        "dropout_rate": 0.12,
        "outlier_rate": 0.03,
        "low_accuracy_rate": 0.10,
        "low_accuracy_m": 80.0,
        "seed": 91,
    }
    plain = _observe(NoisySensor(**shared))
    jittered = _observe(NoisySensor(jitter_sigma_m=4.0, **shared))

    assert [fix.at for fix in plain.fixes] == [fix.at for fix in jittered.fixes]
    assert [fix.at for fix in plain.fixes if fix.accuracy_m == 80.0] == [
        fix.at for fix in jittered.fixes if fix.accuracy_m == 80.0
    ]


def test_dropout_preserves_endpoints_and_accuracy_outliers_reach_canonical_filter():
    motion = _motion()
    perfect = observe_perfectly(
        motion,
        PerfectSensor(),
        session_id="perfect",
        dog_id="dog",
        started_at=START,
        origin_lat=ORIGIN[0],
        origin_lng=ORIGIN[1],
    )
    noisy = _observe(
        NoisySensor(
            dropout_rate=0.2,
            outlier_rate=0.05,
            low_accuracy_rate=0.15,
            low_accuracy_m=80.0,
            seed=7,
        )
    )
    computed = compute_facts(
        noisy.session_id,
        noisy.dog_id,
        noisy.started_at,
        noisy.ended_at,
        list(noisy.fixes),
    )

    assert len(noisy.fixes) < len(perfect.fixes)
    assert noisy.fixes[0].at == perfect.fixes[0].at
    assert noisy.fixes[-1].at == perfect.fixes[-1].at
    assert computed.trail.quality.rejected_low_accuracy > 0
    assert computed.trail.quality.jump_breaks > 0


@pytest.mark.parametrize(
    "kwargs",
    (
        {"dropout_rate": 1.0},
        {"outlier_rate": -0.1},
        {"outlier_rate": 0.1, "outlier_distance_m": 0.0},
        {"jitter_sigma_m": -1.0},
        {"drift_east_m": float("inf")},
    ),
)
def test_invalid_noisy_sensor_contract_fails(kwargs):
    with pytest.raises(ValueError):
        NoisySensor(**kwargs)
