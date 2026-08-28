"""미시 관측 — 판정 이전의 후보 구간. 순수함수 — `Segment`·`GapSpan` 열만 본다.

**왜 남기나**: `MotionEventOccurrence`(정지)는 이미 **판정된 결과**다 — `0.5 m/s 미만이
10 초 이상`. 그 판정이 옳은지가 아직 안 정해졌는데(M2 가 부정 결과를 냈다,
research/2026-08-27-latent-dwell-synthesis.md) `finalize` 는 원좌표를 지운다. 그래서
지금 수집하는 산책은 **문턱을 다시 고를 방법이 없는 과거**가 된다.

이 층은 그 앞에 선다. 후하게 잡은 후보 구간의 (시간 · 거리 · 위치)를 남기고 "이게 체류인가"
는 안 묻는다. 남은 값으로 지표 후보들을 **나중에** 계산한다:

    저속 질량(low-motion)   후보 중 속도 기준을 다시 걸어 고른다
    초과시간(excess-time)   duration_s − path_m / v_ref  — v_ref 는 아래 속도 분포에서

**"모든 미래 지표에 중립" 은 불가능한 약속이다.** 후보를 고르는 문턱 자체가 이미 선택이다.
이 모듈이 약속하는 것은 **선언한 탐색 범위 안에서** 검출기에 독립이라는 것뿐이고, 범위는
`CANDIDATE_SPEED_MPS` 가 정한다. 범위 밖 행동(접근·회피 같은 빠른 미시 행동)을 나중에
탐색하려면 **새 generation 이 필요하고, 이미 purge 된 과거는 그 generation 으로 복구되지
않는다.** 그래서 버전을 값에 박는다 (`MICRO_OBSERVATION_VERSION`) — `curve.py` 와 같은 규율.

## 왜 문턱이 1.0 m/s 인가 — 만성 저속을 놓치지 않으려고

정지(0.5) 보다 후하게 잡는다. **만성 저속 구간**(경사·좁은 골목·횡단 진입부처럼 멈추지는
않는데 늘 느린 자리)은 0.5 문턱 위에 있어서 정지로는 하나도 안 잡히는데, 초과시간 지표를
특이적으로 속이는 것이 바로 그 구간이다. 후보에서 빠지면 **지표 비교 실험 자체가 그 적을
못 본다.** 잠정값이고, 실기기 측정 뒤에 바뀌면 generation 이 오른다.

## 관측된 저속과 비관측 경과를 섞지 않는다

    kind="slow"   관측 중 느렸다        — 점이 있고 거리가 있다
    kind="gap"    관측이 없었다         — 시간만 흘렀고 그 사이는 모른다

이 둘을 한 열에 담으면 **신호 음영이 최고의 가짜 체류가 된다.** 편의점에 들어갔다 나오면
`dt` 는 크고 `dist` 는 작다 — 자리 고정 · 반복 · 길다. 찾으려는 반복 체류와 프로필이 같다.
`facts.py` 가 이미 `dt > 60s` 를 gap 으로 끊어 정지로 만들지 않지만, 그 사실을 **버리지 않고
따로 적어야** 나중에 검출기가 "여기는 관측이 없었다" 를 알 수 있다.

기록하지 **않는** 단절 둘 — 명시적 pause(chain 변경)와 jump(200m 초과). pause 는 앱이 아는
사용자 행위지 신호 음영이 아니고, jump 는 경과시간 이상이 아니라 위치 이상이다. 둘 다
`FixQuality` 가 세고 있다. 이것도 선언한 범위의 일부다.
"""

import math
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime

from app.features.walk.facts import GapSpan, Segment, haversine_m
from app.features.walk.models import WalkFix

MICRO_OBSERVATION_VERSION = 1

# 후보 상한. 이 위는 "평범하게 걷는 중" 으로 보고 안 남긴다 — 선언한 탐색 범위의 경계다.
CANDIDATE_SPEED_MPS = 1.0
# 이보다 짧은 창은 안 남긴다. 점 간격(수 초) 수준의 흔들림까지 행(row)으로 만들지 않는다.
CANDIDATE_MIN_S = 3.0
# 속도 분포를 낼 최소 표본. 이하면 None — 못 만든 것을 만든 척하지 않는다.
MIN_SPEED_SAMPLES = 5


@dataclass(frozen=True)
class MicroObservation:
    """후보 구간 하나. **판정이 아니다** — 이름도 `stop` 이 아니라 `slow` 다."""

    session_id: str
    index: int
    kind: str                    # "slow" | "gap"
    started_at: datetime
    ended_at: datetime
    duration_s: float
    lat: float                   # slow: 창 안 점들의 중심 / gap: 단절 직전 마지막 관측점
    lng: float
    path_m: float                # 창 안 구간 거리 합. 지터 포함 — gap 은 0(관측이 없다)
    net_m: float                 # 창 양 끝점 사이 변위. path 와의 차이가 곧 흔들림이다
    span_m: float                # 중심에서 가장 먼 점까지. 서 있었나 서성였나 — gap 은 0
    fix_count: int
    accuracy_p50_m: float | None
    route_offset_m: float        # 이동거리 기준 동선상 위치. 다른 관측층과 같은 자
    chain_index: int
    abuts_break: bool            # 창의 한쪽 끝이 관측 경계(단절·세션 시작/끝)와 맞닿았나

    def to_row(self) -> dict:
        return {
            "session_id": self.session_id, "observation_index": self.index,
            "kind": self.kind, "started_at": self.started_at, "ended_at": self.ended_at,
            "duration_s": round(self.duration_s, 2),
            "lat": self.lat, "lng": self.lng,
            "path_m": round(self.path_m, 3), "net_m": round(self.net_m, 3),
            "span_m": round(self.span_m, 3), "fix_count": self.fix_count,
            "accuracy_p50_m": self.accuracy_p50_m,
            "route_offset_m": round(self.route_offset_m, 3),
            "chain_index": self.chain_index, "abuts_break": self.abuts_break,
        }


@dataclass(frozen=True)
class MovingSpeedProfile:
    """이동 구간 속도의 분포. **v_ref 를 하나로 굽지 않으려고** 분위수로 남긴다.

    초과시간 지표는 기준 속도 `v_ref` 가 있어야 계산되는데, 그 추정 방식이 아직 안 정해졌다.
    `WalkFacts.avg_speed_mps` 는 평균 하나뿐이라 만성 저속 구간이 섞이면 같이 낮아진다 —
    체류가 많은 사람일수록 기준이 낮아져 초과가 작게 읽히는 자가 오염이 여기서도 생긴다.
    분위수를 남겨 두면 나중에 p50·p70·p80 중 무엇이 나은지 **자료로 고를 수 있다.**

    좌표 없음 — 어디를 걸었는지 나오지 않는다 (`curve.py` 와 같은 성격).
    """

    p50: float
    p70: float
    p80: float
    p90: float
    sample_n: int

    def to_dict(self) -> dict:
        return {"p50": round(self.p50, 3), "p70": round(self.p70, 3),
                "p80": round(self.p80, 3), "p90": round(self.p90, 3),
                "sample_n": self.sample_n}


def _percentile(ordered: list[float], q: float) -> float:
    """선형 보간 분위수. `statistics.quantiles` 는 표본이 적을 때 경계 처리가 달라진다."""
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * q
    low, high = math.floor(k), math.ceil(k)
    if low == high:
        return ordered[int(k)]
    return ordered[low] * (high - k) + ordered[high] * (k - low)


def moving_speed_profile(segments: list[Segment]) -> MovingSpeedProfile | None:
    """이동으로 분류된 구간의 속도 분포. 표본이 모자라면 None."""
    speeds = sorted(s.dist / s.dt for s in segments if s.moving and s.dt > 0)
    if len(speeds) < MIN_SPEED_SAMPLES:
        return None
    return MovingSpeedProfile(
        p50=_percentile(speeds, 0.50), p70=_percentile(speeds, 0.70),
        p80=_percentile(speeds, 0.80), p90=_percentile(speeds, 0.90),
        sample_n=len(speeds),
    )


def _window(session_id: str, run: list[Segment], *, abuts_break: bool) -> MicroObservation:
    """연속한 저속 구간 묶음 하나 → 관측 한 줄."""
    points: list[WalkFix] = [run[0].a] + [seg.b for seg in run]
    duration = sum(seg.dt for seg in run)
    path = sum(seg.dist for seg in run)
    lat = sum(p.lat for p in points) / len(points)
    lng = sum(p.lng for p in points) / len(points)
    centre = WalkFix(client_seq=0, at=run[0].a.at, lat=lat, lng=lng)
    accuracies = [p.accuracy_m for p in points if p.accuracy_m is not None]
    return MicroObservation(
        session_id=session_id, index=0, kind="slow",
        started_at=run[0].a.at.astimezone(UTC), ended_at=run[-1].b.at.astimezone(UTC),
        duration_s=duration, lat=lat, lng=lng,
        path_m=path, net_m=haversine_m(run[0].a, run[-1].b),
        span_m=max(haversine_m(centre, p) for p in points),
        fix_count=len(points),
        accuracy_p50_m=round(statistics.median(accuracies), 2) if accuracies else None,
        route_offset_m=run[0].offset_m, chain_index=run[0].chain_index,
        abuts_break=abuts_break,
    )


def _gap_observation(session_id: str, gap: GapSpan) -> MicroObservation:
    """비관측 경과 하나. 위치는 **단절 직전 마지막으로 본 곳**이다 — 그 뒤는 모른다."""
    accuracies = [f.accuracy_m for f in (gap.a, gap.b) if f.accuracy_m is not None]
    return MicroObservation(
        session_id=session_id, index=0, kind="gap",
        started_at=gap.a.at.astimezone(UTC), ended_at=gap.b.at.astimezone(UTC),
        duration_s=gap.dt, lat=gap.a.lat, lng=gap.a.lng,
        path_m=0.0, net_m=haversine_m(gap.a, gap.b), span_m=0.0,
        fix_count=2,
        accuracy_p50_m=round(statistics.median(accuracies), 2) if accuracies else None,
        route_offset_m=gap.offset_m, chain_index=gap.chain_index, abuts_break=True,
    )


def extract_observations(
    session_id: str, segments: list[Segment], gaps: list[GapSpan] = ()
) -> list[MicroObservation]:
    """후보 구간을 뽑는다. 문턱은 하나뿐이고 그게 곧 선언한 탐색 범위다.

    묶는 규칙: 속도가 `CANDIDATE_SPEED_MPS` 미만인 구간이 **같은 chain 안에서 연속**하면 한
    창이다. chain 이 바뀌는 자리는 `facts.py` 가 단절(gap·jump·거부·명시적 pause)에서 올린
    것이라, chain 을 넘겨 묶으면 단절 양쪽을 한 번의 체류로 잇게 된다.

    `abuts_break` 는 창이 chain 의 처음이나 끝에 닿았을 때 참이다. 세션의 첫/끝 chain 도
    포함한다 — 기록이 시작되기 전부터 서 있었을 수 있고, 그것도 "창 밖을 모른다" 는 같은
    사실이다.
    """
    runs: list[tuple[list[Segment], bool]] = []
    chain_bounds: dict[int, tuple[int, int]] = {}
    for i, seg in enumerate(segments):
        first, _ = chain_bounds.get(seg.chain_index, (i, i))
        chain_bounds[seg.chain_index] = (first, i)

    run: list[Segment] = []
    start_i = 0
    for i, seg in enumerate(segments):
        slow = seg.dt > 0 and seg.dist / seg.dt < CANDIDATE_SPEED_MPS
        contiguous = bool(run) and seg.chain_index == run[-1].chain_index
        if slow and (contiguous or not run):
            if not run:
                start_i = i
            run.append(seg)
            continue
        if run:
            runs.append((run, _touches_edge(run, start_i, i - 1, chain_bounds)))
            run = []
        if slow:
            start_i = i
            run = [seg]
    if run:
        runs.append((run, _touches_edge(run, start_i, len(segments) - 1, chain_bounds)))

    out = [_window(session_id, r, abuts_break=edge)
           for r, edge in runs if sum(s.dt for s in r) >= CANDIDATE_MIN_S]
    out.extend(_gap_observation(session_id, g) for g in gaps)
    out.sort(key=lambda o: (o.started_at, o.kind))
    return [MicroObservation(**{**vars(o), "index": i}) for i, o in enumerate(out)]


def _touches_edge(run: list[Segment], start_i: int, end_i: int,
                  bounds: dict[int, tuple[int, int]]) -> bool:
    first, last = bounds[run[0].chain_index]
    return start_i == first or end_i == last
