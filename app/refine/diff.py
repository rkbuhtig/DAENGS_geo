"""상태 diff → 사람이 읽는 changes. **정책별로 묶어서** 낸다.

서버가 만든다. LLM이 "좁혔어요"라 말해놓고 실제론 안 바뀐 상황을 막는 장치.
target 변경은 "결과가 바뀐다", journey 변경은 "같은 결과, 가는 방법이 바뀐다" — 사용자에게 다르게 읽혀야 한다.
"""

from app.refine.state import SearchState

_LABEL = {
    "recommended": "추천", "main_road": "큰길 우선", "shortest": "최단", "no_stairs": "계단 제외",
    "walk": "도보", "car": "차량", "transit": "대중교통",
    "distance": "거리순", "duration": "소요시간순", "open_first": "영업중 우선",
    "ortho": "정형", "eye": "안과", "dental": "치과", "derma": "피부", "cardio": "심장", "rehab": "재활",
    "24h": "24시", "center": "의료센터", "secondary": "2차", "surgery": "외과",
    "stairs": "계단", "underpass": "지하도", "overpass": "육교",
}
POLICY_LABEL = {"target": "찾는 곳", "journey": "가는 길", "view": "보기"}


def _l(v) -> str:
    return _LABEL.get(v, str(v))


def _fmt_m(m: int) -> str:
    return f"{m/1000:g}km" if m >= 1000 else f"{m}m"


def changes_by_policy(before: SearchState | None, after: SearchState) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"target": [], "journey": [], "view": []}
    if before is None:
        out["target"].append(f"초안: 반경 {_fmt_m(after.target.radius_m)}, 필터 없음")
        return out

    bt, at_ = before.target, after.target
    bj, aj = before.journey, after.journey

    # ---- target: 결과 집합이 바뀐다
    if (before.lat, before.lng) != (after.lat, after.lng):
        out["target"].append("기준 위치 변경")
    if bt.radius_m != at_.radius_m:
        out["target"].append(f"반경 {_fmt_m(bt.radius_m)} → {_fmt_m(at_.radius_m)}")
    for f, on, off in (("open_now", "지금 영업중만", "영업중 필터 해제"),
                       ("night", "야간 진료만", "야간 필터 해제"),
                       ("emergency", "응급만", "응급 필터 해제")):
        if getattr(bt, f) != getattr(at_, f):
            out["target"].append(on if getattr(at_, f) else off)
    if bt.specialty != at_.specialty:
        out["target"].append("특화: " + (", ".join(_l(t) for t in at_.specialty) or "없음"))
    if bt.require_tags != at_.require_tags:
        out["target"].append("필수: " + (", ".join(_l(t) for t in at_.require_tags) or "없음"))
    added = set(at_.exclude_ids) - set(bt.exclude_ids)
    if added:
        out["target"].append(f"{len(added)}곳 제외")
    if set(at_.pin_ids) - set(bt.pin_ids):
        out["target"].append("고정 추가")

    # ---- journey: 결과는 그대로, 가는 방법만
    if bj.mode != aj.mode:
        out["journey"].append(f"이동수단: {_l(aj.mode) if aj.mode else '미지정'}")
    if bj.walk.option != aj.walk.option:
        out["journey"].append(f"도보 옵션: {_l(aj.walk.option)}")
    if bj.walk.avoid != aj.walk.avoid:
        out["journey"].append("피하기: " + (", ".join(_l(t) for t in aj.walk.avoid) or "없음"))
    if (bj.max_min, bj.hard_limit) != (aj.max_min, aj.hard_limit):
        if aj.max_min is None:
            out["journey"].append("시간 제한 해제")
        else:
            out["journey"].append(f"{aj.max_min}분 이내" + (" (초과 제외)" if aj.hard_limit else " (표시만)"))

    # ---- view
    if before.sort != after.sort:
        out["view"].append(f"정렬: {_l(after.sort)}")
    return out


def changes(before: SearchState | None, after: SearchState) -> list[str]:
    g = changes_by_policy(before, after)
    flat = g["target"] + g["journey"] + g["view"]
    return flat or ["변경 없음"]
