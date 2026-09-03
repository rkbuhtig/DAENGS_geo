"""여러 feature의 산책 투영을 조립하는 모바일 Spatial Diary dev-console 표면.

제품 API나 저장 원본이 아니다. 결정론적 산책 fixture를 canonical facts/Paint 경로에 넣어
브라우저와 이후 Android 구현이 같은 화면 상태를 읽을 수 있게 한다.
"""

from datetime import datetime, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

from app.features.territory.paint import NARROW_STEP, paint_sheet
from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkFix
from app.geo.cells import hex_boundary_latlng

_KST = ZoneInfo("Asia/Seoul")
_START = datetime(2026, 8, 4, 19, 10, tzinfo=_KST)
_RADIUS_U = 8.0
_READ_RADIUS_M = 45.0

# 서울숲 근방의 결정론적 UI fixture. 실제 장소나 실제 사용자 산책을 뜻하지 않는다.
_POINTS = {
    "home": (37.54445, 127.03805),
    "gate": (37.54496, 127.03852),
    "fork": (37.54548, 127.03904),
    "park": (37.54612, 127.03975),
    "north": (37.54677, 127.04038),
    "east": (37.54568, 127.04016),
    "stream": (37.54494, 127.04073),
    "south": (37.54418, 127.04014),
    "alley": (37.54373, 127.03922),
}

_ROUTES = (
    ("home", "gate", "fork", "park", "north", "park", "fork", "gate", "home"),
    ("home", "gate", "fork", "east", "stream", "east", "fork", "gate", "home"),
    ("home", "gate", "fork", "park", "park", "north", "park", "fork", "gate", "home"),
    ("home", "gate", "fork", "east", "stream", "south", "alley", "gate", "home"),
    ("home", "gate", "fork", "park", "north", "park", "fork", "east", "stream"),
    ("home", "gate", "fork", "east", "stream", "stream", "south", "alley", "home"),
    ("home", "gate", "fork", "park", "north", "park", "fork", "gate", "home"),
    ("home", "gate", "fork", "east", "stream", "east", "fork", "park", "north"),
    ("home", "gate", "alley", "south", "stream", "east", "fork", "gate", "home"),
    ("home", "gate", "fork", "park", "park", "north", "park", "fork", "gate"),
    ("home", "gate", "fork", "east", "stream", "south", "alley", "gate", "home"),
    ("home", "gate", "fork", "park", "north", "park", "fork", "east", "stream"),
)

_SESSION_META = (
    (("choco",), "dry", "night"),
    (("bori",), "dry", "day"),
    (("choco", "bori"), "rain", "night"),
    (("choco",), "dry", "night"),
    (("bori",), "rain", "day"),
    (("choco", "bori"), "dry", "day"),
    (("choco",), "dry", "night"),
    (("bori",), "rain", "night"),
    (("choco", "bori"), "dry", "day"),
    (("choco",), "rain", "night"),
    (("bori",), "dry", "day"),
    (("choco", "bori"), "dry", "night"),
)

_SESSION_TITLES = (
    "초코와 천천히 동네를 돈 저녁",
    "보리가 물가 쪽을 바라본 오후",
    "비가 그친 뒤 공원으로 간 날",
    "초코와 익숙한 갈림길을 지난 밤",
    "빗소리를 들으며 북쪽 길로",
    "둘이 물빛산책로까지 내려간 아침",
    "나무 그늘에서 오래 머문 저녁",
    "보리가 먼저 물가를 고른 밤",
    "새롬길 골목으로 돌아온 오후",
    "초코가 익숙한 입구를 고른 밤",
    "보리와 물빛산책로를 돈 날",
    "둘이 공원과 물가를 잇던 저녁",
)

_SPEED_PATTERN = ("slow", "normal", "fast", "slow", "stopped", "normal", "slow", "normal")


def _walk_fixes(route: tuple[str, ...], started_at: datetime) -> list[WalkFix]:
    return [
        WalkFix(
            client_seq=index,
            chain_index=0,
            at=started_at + timedelta(seconds=index * 24),
            lat=_POINTS[name][0],
            lng=_POINTS[name][1],
            accuracy_m=6.0,
            is_mock=True,
        )
        for index, name in enumerate(route)
    ]


def _cell_payload(sheet) -> list[dict[str, object]]:
    cells = []
    for q, r in sorted(sheet.occupancy):
        cells.append(
            {
                "id": f"{sheet.grid_version}:{sheet.radius_u:g}:{q}:{r}",
                "q": q,
                "r": r,
                "boundary": [
                    [round(lat, 7), round(lng, 7)]
                    for lat, lng in hex_boundary_latlng(q, r, sheet.radius_u)
                ],
                "occupancy_s": round(sheet.occupancy[(q, r)], 8),
                "peak": round(sheet.peak[(q, r)], 8),
            }
        )
    return cells


def _pin(
    *,
    pin_id: str,
    session_id: str,
    point_name: str,
    event_at: datetime,
    title: str,
    summary: str,
    narration: str,
    participants: tuple[str, ...],
    context_label: str,
    place_label: str,
    behavior_label: str,
    event_index: int = 0,
) -> dict[str, object]:
    return {
        "pin_id": pin_id,
        "session_id": session_id,
        "point": list(_POINTS[point_name]),
        "event_at": event_at.isoformat(),
        "event_index": event_index,
        "read_radius_m": _READ_RADIUS_M,
        "title": title,
        "summary": summary,
        "narration": narration,
        "participants": list(participants),
        "context_label": context_label,
        "place_label": place_label,
        "behavior_label": behavior_label,
    }


def _route_payload(route: tuple[str, ...], started_at: datetime) -> dict[str, object]:
    """영구 계약이 아닌, 단일 세션 UI 검증용 단순화 경로."""
    points = [list(_POINTS[name]) for name in route]
    segments = []
    for index, (start, end) in enumerate(pairwise(points)):
        segments.append(
            {
                "from": start,
                "to": end,
                "started_at": (started_at + timedelta(seconds=index * 24)).isoformat(),
                "ended_at": (started_at + timedelta(seconds=(index + 1) * 24)).isoformat(),
                "speed_band": _SPEED_PATTERN[index % len(_SPEED_PATTERN)],
                "accuracy_m": 6.0,
            }
        )
    return {
        "storage": "fixture_only_simplified_route",
        "segments": segments,
        "approximate_start": points[0],
        "approximate_end": points[-1],
    }


def build_spatial_diary_ui_fixture() -> dict[str, object]:
    sheets = []
    sessions = []
    started_by_session: dict[str, datetime] = {}
    participants_by_session: dict[str, tuple[str, ...]] = {}
    paint_fps: set[str] = set()

    for index, (route, meta) in enumerate(zip(_ROUTES, _SESSION_META, strict=True), start=1):
        participants, precipitation, daylight = meta
        started_at = _START + timedelta(days=(index - 1) * 2, minutes=index * 7)
        session_id = f"ui-walk-{index:02d}"
        fixes = _walk_fixes(route, started_at)
        computed = compute_facts(session_id, participants[0], started_at, fixes[-1].at, fixes)
        sheet = paint_sheet(session_id, started_at, computed.segments, _RADIUS_U, NARROW_STEP)
        paint_fps.add(sheet.paint_fp)
        started_by_session[session_id] = started_at
        participants_by_session[session_id] = participants
        sheets.append(
            {
                "session_id": session_id,
                "started_at": started_at.isoformat(),
                "participants": list(participants),
                "precipitation": precipitation,
                "daylight": daylight,
                "source_segment_s": round(sum(segment.dt for segment in computed.segments), 8),
                "occupancy_mass_s": round(sum(sheet.occupancy.values()), 8),
                "cells": _cell_payload(sheet),
            }
        )
        participant_names = "와 ".join("초코" if pet == "choco" else "보리" for pet in participants)
        sessions.append(
            {
                "session_id": session_id,
                "started_at": started_at.isoformat(),
                "ended_at": fixes[-1].at.isoformat(),
                "participants": list(participants),
                "precipitation": precipitation,
                "daylight": daylight,
                "title": _SESSION_TITLES[index - 1],
                "summary": f"{participant_names} 함께 걸으며 남긴 한 번의 산책 기록이에요.",
                "narration": "선을 따라가면 시작부터 끝까지의 움직임과 사건 순서를 함께 읽을 수 있어요.",
                "duration_s": computed.facts.duration_s,
                "moving_distance_m": computed.facts.moving_distance_m,
                "route": _route_payload(route, started_at),
            }
        )

    if len(paint_fps) != 1:
        raise RuntimeError("UI fixture Cellophane paint 세대가 갈렸다")

    pins = [
        _pin(
            pin_id="pin-gate-03",
            session_id="ui-walk-03",
            point_name="gate",
            event_at=started_by_session["ui-walk-03"] + timedelta(seconds=24),
            event_index=1,
            title="입구에서 비 냄새를 확인",
            summary="둘이 같은 방향을 바라보다가 공원 쪽으로 움직였어요.",
            narration="초코와 보리가 입구에서 잠깐 멈춰 젖은 풀 냄새를 확인했어요.",
            participants=participants_by_session["ui-walk-03"],
            context_label="비 온 뒤 · 밤",
            place_label="늘봄공원 입구",
            behavior_label="함께 멈춤",
        ),
        _pin(
            pin_id="pin-park-03",
            session_id="ui-walk-03",
            point_name="park",
            event_at=started_by_session["ui-walk-03"] + timedelta(seconds=92),
            event_index=2,
            title="비가 그친 뒤 공원으로 간 날",
            summary="초코와 보리가 젖은 길을 천천히 걸었던 저녁 산책이에요.",
            narration="늘봄공원 입구에서 두 아이가 함께 멈춰 주변을 오래 살폈어요.",
            participants=participants_by_session["ui-walk-03"],
            context_label="비 온 뒤 · 밤",
            place_label="늘봄공원 안쪽",
            behavior_label="주변 살피기",
        ),
        _pin(
            pin_id="pin-north-03",
            session_id="ui-walk-03",
            point_name="north",
            event_at=started_by_session["ui-walk-03"] + timedelta(seconds=120),
            event_index=3,
            title="나무 아래에서 잠깐 쉼",
            summary="돌아가기 전에 나무 아래에서 호흡을 고른 장면이에요.",
            narration="보리가 먼저 앉고 초코가 곁에 서서 잠시 쉬었다가 돌아왔어요.",
            participants=participants_by_session["ui-walk-03"],
            context_label="비 온 뒤 · 밤",
            place_label="북쪽 나무 그늘",
            behavior_label="함께 휴식",
        ),
        _pin(
            pin_id="pin-park-10",
            session_id="ui-walk-10",
            point_name="park",
            event_at=started_by_session["ui-walk-10"] + timedelta(seconds=98),
            title="초코가 익숙한 입구를 고른 밤",
            summary="공원 쪽으로 먼저 방향을 잡고 평소보다 짧게 둘러봤어요.",
            narration="초코가 공원 입구에서 잠깐 멈춘 뒤 북쪽 길로 먼저 움직였어요.",
            participants=participants_by_session["ui-walk-10"],
            context_label="비 · 밤",
            place_label="늘봄공원 안쪽",
            behavior_label="방향 선택",
        ),
        _pin(
            pin_id="pin-stream-06",
            session_id="ui-walk-06",
            point_name="stream",
            event_at=started_by_session["ui-walk-06"] + timedelta(seconds=118),
            title="물가에서 냄새를 오래 맡은 아침",
            summary="두 아이가 물빛산책로까지 내려가 천천히 돌아온 산책이에요.",
            narration="물가 가장자리에서 냄새를 맡으며 한동안 같은 자리에 머물렀어요.",
            participants=participants_by_session["ui-walk-06"],
            context_label="맑음 · 낮",
            place_label="물빛산책로",
            behavior_label="냄새 맡기",
        ),
        _pin(
            pin_id="pin-stream-11",
            session_id="ui-walk-11",
            point_name="stream",
            event_at=started_by_session["ui-walk-11"] + timedelta(seconds=112),
            title="보리와 물빛산책로를 돈 날",
            summary="익숙한 갈림길을 지나 물가를 따라 남쪽으로 걸었어요.",
            narration="보리가 물가 쪽을 바라보다가 남쪽 산책로로 방향을 골랐어요.",
            participants=participants_by_session["ui-walk-11"],
            context_label="맑음 · 낮",
            place_label="물빛산책로",
            behavior_label="방향 선택",
        ),
        _pin(
            pin_id="pin-alley-09",
            session_id="ui-walk-09",
            point_name="alley",
            event_at=started_by_session["ui-walk-09"] + timedelta(seconds=76),
            title="새롬길 골목으로 돌아온 오후",
            summary="공원 대신 남쪽 골목을 지나 집으로 돌아온 산책이에요.",
            narration="갈림길에서 두 아이가 새롬길 쪽으로 방향을 바꿨어요.",
            participants=participants_by_session["ui-walk-09"],
            context_label="맑음 · 낮",
            place_label="새롬길 골목",
            behavior_label="방향 전환",
        ),
    ]

    paint_fp = next(iter(paint_fps))
    return {
        "fixture_version": 2,
        "generated_for": "spatial-diary-mobile-ui-lab",
        "experimental_contract": {
            "route_is_persisted": False,
            "note": "route와 approximate endpoint는 단일 세션 UI 검증용 fixture이며 현재 영구 계약이 아니다",
        },
        "viewport": {"center": list(_POINTS["fork"]), "zoom": 16},
        "paint": {
            "paint_fp": paint_fp,
            "radius_u": _RADIUS_U,
            "profile_name": NARROW_STEP.name,
            "brush_bands_m": list(NARROW_STEP.bands),
            "brush_reach_m": NARROW_STEP.reach_m,
        },
        "display": {"sheet_alpha": 0.105, "min_peak": 0.15},
        "sheets": sheets,
        "sessions": sessions,
        "pins": pins,
    }
