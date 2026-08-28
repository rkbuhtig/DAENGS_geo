"""미시 관측 층 — **원좌표 없이 지표를 다시 계산할 수 있나.**

이 파일의 존재 이유는 수용 기준 하나다: `finalize` 가 fix 를 지운 뒤에도 저속 질량과
초과시간을 관측만으로 복원할 수 있어야 한다. 못 하면 이 층은 있으나 마나다.

occupancy(전체 노출)와 prominence(주변 대비)는 여기 없다 — 그건 셀로판(거시 기억판)의
일이고 결정 #69 가 정한 층이다. 미시 원장이 답하는 것은 저속 질량과 초과시간까지다.
"""

import math
from datetime import UTC, datetime, timedelta

from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkFix
from app.features.walk.observation import (
    CANDIDATE_MIN_S,
    CANDIDATE_SPEED_MPS,
    extract_observations,
    moving_speed_profile,
)

T0 = datetime(2026, 8, 28, 7, 0, tzinfo=UTC)
LAT0, LNG0 = 37.4900, 127.0500
M_PER_DEG_LAT = 111_320.0


def fixes_from(steps: list[tuple[float, float]], *, start_seq: int = 0) -> list[WalkFix]:
    """(초, 그 초 동안 북쪽으로 이동한 m) 목록 → fix 열. 1 초 간격 가정 없음."""
    out: list[WalkFix] = []
    t, north = 0.0, 0.0
    out.append(WalkFix(client_seq=start_seq, at=T0, lat=LAT0, lng=LNG0, accuracy_m=5.0))
    for dt, dist in steps:
        t += dt
        north += dist
        out.append(WalkFix(client_seq=start_seq + len(out), at=T0 + timedelta(seconds=t),
                           lat=LAT0 + north / M_PER_DEG_LAT, lng=LNG0, accuracy_m=5.0))
    return out


def walk_with(steps: list[tuple[float, float]]):
    fixes = fixes_from(steps)
    return compute_facts("s:obs", "dubu", T0, fixes[-1].at + timedelta(seconds=1), fixes)


def _one(computed) -> tuple[str, list, list]:
    return "s:obs", computed.segments, computed.gaps


# ---------------------------------------------------------------- 수용 기준
def _low_motion_mass_from_raw(computed, threshold: float) -> float:
    return sum(s.dt for s in computed.segments if s.dist / s.dt < threshold)


def _low_motion_mass_from_observations(observations, threshold: float) -> float:
    """관측만으로 같은 값을 낸다 — 창의 평균 속도로 다시 문턱을 건다."""
    return sum(o.duration_s for o in observations
               if o.kind == "slow" and o.path_m / o.duration_s < threshold)


def _excess_from_raw(computed, v_ref: float) -> float:
    return sum(max(0.0, s.dt - s.dist / v_ref) for s in computed.segments)


def _excess_from_observations(observations, v_ref: float) -> float:
    return sum(max(0.0, o.duration_s - o.path_m / v_ref)
               for o in observations if o.kind == "slow")


def test_low_motion_mass_survives_without_raw_fixes():
    """정지 문턱(0.5)을 나중에 다시 걸어도 관측만으로 같은 질량이 나온다."""
    computed = walk_with(
        [(1.0, 1.2)] * 20 + [(1.0, 0.1)] * 30 + [(1.0, 1.2)] * 20   # 걷다 서다 걷다
    )
    observations = extract_observations("s:obs", computed.segments, computed.gaps)

    raw = _low_motion_mass_from_raw(computed, 0.5)
    kept = _low_motion_mass_from_observations(observations, 0.5)
    assert raw > 25  # 실제로 정지가 있었다
    assert math.isclose(raw, kept, rel_tol=1e-6)


def test_excess_time_survives_when_v_ref_comes_from_the_walk_itself():
    """초과시간은 구간별 (시간·거리)가 있어야 계산된다. 관측이 그걸 들고 있다.

    `v_ref` 를 **그 산책의 이동 속도 분포에서** 뽑으면 창 밖(빠르게 걸은 구간)의 초과가
    정의상 0 이라 관측만으로 정확히 복원된다. 그게 v_ref 를 남의 상수가 아니라 자기
    분포에서 얻어야 하는 이유이기도 하다.
    """
    computed = walk_with([(1.0, 1.2)] * 30 + [(1.0, 0.1)] * 40 + [(1.0, 1.2)] * 30)
    observations = extract_observations("s:obs", computed.segments, computed.gaps)
    profile = moving_speed_profile(computed.segments)

    for v_ref in (0.9, 1.0, profile.p50, profile.p70, profile.p80):
        raw = _excess_from_raw(computed, v_ref)
        kept = _excess_from_observations(observations, v_ref)
        assert raw > 30
        # 정확히 같지는 않다: 분위수는 표본 하나에 걸치므로 그보다 아주 조금 느린 보행
        # 구간이 남고, 그 몫(1e-8 초 수준)은 창 밖이라 관측에 없다. 아래 leak 테스트가
        # 같은 성질을 실제로 문제가 되는 크기에서 고정한다.
        assert math.isclose(raw, kept, rel_tol=1e-6), (v_ref, raw, kept)


def test_excess_leaks_when_v_ref_exceeds_the_walking_speed():
    """선언한 범위의 경계를 테스트로 박는다 — 여기서부터는 관측만으로 복원이 안 된다.

    `v_ref` 가 실제 보행 속도보다 높으면 **평범하게 걷는 구간에서도** 초과가 쌓이는데,
    그 구간은 후보 문턱 위라 이 층에 없다. 이건 저장의 결함이 아니라 지표의 성질이다 —
    자기 분포 위에서 v_ref 를 고르면 생기지 않는다. 나중에 그런 v_ref 를 쓰고 싶어지면
    새 generation 이 필요하다.
    """
    computed = walk_with([(1.0, 1.2)] * 30 + [(1.0, 0.1)] * 40 + [(1.0, 1.2)] * 30)
    observations = extract_observations("s:obs", computed.segments, computed.gaps)

    raw = _excess_from_raw(computed, 1.44)              # 실제 보행 1.2 보다 20% 높다
    kept = _excess_from_observations(observations, 1.44)
    assert kept < raw * 0.85                            # 걷는 구간 몫이 통째로 빠진다


def test_chronic_slow_zone_is_kept_although_it_is_never_a_stop():
    """만성 저속(0.5~1.0)은 정지로 하나도 안 잡히는데 초과시간을 특이적으로 속인다.

    후보 문턱이 정지 문턱과 같았다면 이 구간이 통째로 사라져서 지표 비교 실험이 그 적을
    아예 못 본다. 이 테스트가 `CANDIDATE_SPEED_MPS` 가 후한 이유를 고정한다.
    """
    computed = walk_with([(1.0, 1.2)] * 20 + [(1.0, 0.72)] * 60 + [(1.0, 1.2)] * 20)
    observations = extract_observations("s:obs", computed.segments, computed.gaps)

    assert computed.facts.stop_count == 0            # 정지로는 하나도 안 잡힌다
    slow = [o for o in observations if o.kind == "slow"]
    assert slow and sum(o.duration_s for o in slow) >= 55
    assert _excess_from_observations(observations, 1.2) > 20


def test_gap_is_recorded_as_absence_not_as_dwell():
    """신호 음영은 자리 고정·반복·길다 — 반복 체류와 프로필이 같은 최악의 가짜다."""
    fixes = fixes_from([(1.0, 1.2)] * 20)
    resumed_at = fixes[-1].at + timedelta(seconds=180)     # 3 분 관측 없음
    fixes.append(WalkFix(client_seq=len(fixes), at=resumed_at,
                         lat=fixes[-1].lat + 5 / M_PER_DEG_LAT, lng=LNG0, accuracy_m=5.0))
    fixes += [WalkFix(client_seq=len(fixes) + i,
                      at=resumed_at + timedelta(seconds=i + 1),
                      lat=fixes[-1].lat + (i + 1) * 1.2 / M_PER_DEG_LAT,
                      lng=LNG0, accuracy_m=5.0) for i in range(20)]
    computed = compute_facts("s:obs", "dubu", T0, fixes[-1].at + timedelta(seconds=1), fixes)
    observations = extract_observations("s:obs", computed.segments, computed.gaps)

    gaps = [o for o in observations if o.kind == "gap"]
    assert len(gaps) == 1
    assert math.isclose(gaps[0].duration_s, 180.0, rel_tol=1e-6)
    assert gaps[0].path_m == 0.0 and gaps[0].span_m == 0.0   # 관측이 없으면 거리도 없다
    assert gaps[0].net_m > 4.0                               # 다시 보였을 때 5m 옆이었다
    # 저속 질량·초과시간 어디에도 안 섞인다 — 3 분이 체류로 둔갑하면 안 된다
    assert _low_motion_mass_from_observations(observations, 0.5) < 1.0
    assert _excess_from_observations(observations, 1.2) < 1.0
    assert computed.facts.stop_count == 0


def test_windows_do_not_span_a_break():
    """단절 양쪽을 한 번의 체류로 잇지 않는다 — chain 이 다르면 다른 창이다."""
    slow_a = fixes_from([(1.0, 0.1)] * 20)
    resumed = slow_a[-1].at + timedelta(seconds=180)
    slow_b = [WalkFix(client_seq=len(slow_a) + i, at=resumed + timedelta(seconds=i),
                      lat=slow_a[-1].lat, lng=LNG0, accuracy_m=5.0) for i in range(20)]
    fixes = slow_a + slow_b
    computed = compute_facts("s:obs", "dubu", T0, fixes[-1].at + timedelta(seconds=1), fixes)
    observations = extract_observations("s:obs", computed.segments, computed.gaps)

    slow = [o for o in observations if o.kind == "slow"]
    assert len(slow) == 2                              # 하나로 합쳐지지 않았다
    assert {o.chain_index for o in slow} == {0, 1}
    assert all(o.abuts_break for o in slow)            # 양쪽 다 단절에 닿아 있다


def test_short_wobbles_are_not_rows():
    """점 간격 수준의 흔들림까지 행으로 만들지 않는다."""
    computed = walk_with([(1.0, 1.2)] * 20 + [(1.0, 0.1)] * 2 + [(1.0, 1.2)] * 20)
    observations = extract_observations("s:obs", computed.segments, computed.gaps)
    assert [o for o in observations if o.duration_s < CANDIDATE_MIN_S] == []


def test_path_net_and_span_are_three_different_facts():
    """같은 시간 같은 자리로 보여도 서 있었나 · 서성였나 · 훑었나는 다른 사실이다.

    처음에 `span_m` 하나로 서 있음과 서성임을 가르려다 틀렸다 — 제자리 왕복은 **공간
    범위가 작다.** 가르는 것은 `path_m / net_m`(얼마나 헛돌았나)이고, `span_m` 은 창이
    공간을 얼마나 넓게 덮었나를 따로 말한다. 셋을 한 값으로 접으면 안 되는 이유다.
    """
    still = extract_observations(*_one(walk_with([(1.0, 0.02)] * 40)))[0]
    milling = extract_observations(*_one(walk_with([(1.0, 0.6), (1.0, -0.6)] * 20)))[0]
    sweeping = extract_observations(*_one(walk_with([(1.0, 0.3)] * 40)))[0]

    # 헛돎: 왕복은 경로가 길고 변위가 없다. 서 있음은 둘 다 작다
    assert milling.path_m > 20 and milling.net_m < 0.1
    assert still.path_m < 1.0 and still.net_m < 1.0
    # 공간 범위: 제자리 왕복은 좁고, 한 방향으로 훑으면 넓다
    assert milling.span_m < 1.0
    assert sweeping.span_m > milling.span_m * 5
    # 그런데 훑은 구간은 헛돈 것이 아니다 — path 와 net 이 같다
    assert math.isclose(sweeping.path_m, sweeping.net_m, rel_tol=1e-6)


def test_speed_profile_is_recorded_or_honestly_absent():
    """v_ref 를 하나로 굽지 않는다 — 분위수를 남기고 고르는 건 나중이다."""
    computed = walk_with([(1.0, 1.2)] * 30 + [(1.0, 0.72)] * 30)
    profile = moving_speed_profile(computed.segments)
    assert profile is not None
    assert profile.p50 <= profile.p70 <= profile.p80 <= profile.p90
    # 만성 저속(0.72)이 섞여 평균은 끌려 내려가지만 상위 분위수는 버틴다
    assert profile.p80 > 1.0
    assert profile.sample_n >= 30

    too_short = walk_with([(1.0, 1.2)] * 2)
    assert moving_speed_profile(too_short.segments) is None   # 없는 것을 지어내지 않는다


def test_threshold_is_the_declared_exploration_range():
    """문턱 위 행동은 이 층에 없다 — 범위를 넓히려면 새 generation 이다."""
    fast = walk_with([(1.0, CANDIDATE_SPEED_MPS + 0.3)] * 40)
    assert extract_observations("s:obs", fast.segments, fast.gaps) == []
