"""상태 diff → 사람이 읽는 changes[]. 서버가 만든다. LLM이 "좁혔어요"라 말해놓고 안 바뀐 상황 방지."""

from app.refine.state import SearchState

_LABEL = {
    "recommended": "추천", "main_road": "큰길 우선", "shortest": "최단", "no_stairs": "계단 제외",
    "walk": "도보", "car": "차량", "transit": "대중교통",
    "distance": "거리순", "duration": "소요시간순", "open_first": "영업중 우선",
    "ortho": "정형", "eye": "안과", "dental": "치과", "derma": "피부", "cardio": "심장", "rehab": "재활",
    "24h": "24시", "center": "의료센터", "secondary": "2차", "surgery": "외과",
    "stairs": "계단", "underpass": "지하도", "overpass": "육교",
}


def _l(v) -> str:
    return _LABEL.get(v, str(v))


def _fmt_m(m: int) -> str:
    return f"{m/1000:g}km" if m >= 1000 else f"{m}m"


def changes(before: SearchState | None, after: SearchState) -> list[str]:
    if before is None:
        return ["초안: 반경 " + _fmt_m(after.radius_m) + ", 필터 없음"]
    out: list[str] = []
    b, a = before, after
    if (b.lat, b.lng) != (a.lat, a.lng):
        out.append("기준 위치 변경")
    if b.radius_m != a.radius_m:
        out.append(f"반경 {_fmt_m(b.radius_m)} → {_fmt_m(a.radius_m)}")
    for f, on, off in (("open_now", "지금 영업중만", "영업중 필터 해제"),
                       ("night", "야간 진료만", "야간 필터 해제"),
                       ("emergency", "응급만", "응급 필터 해제")):
        if getattr(b, f) != getattr(a, f):
            out.append(on if getattr(a, f) else off)
    if b.specialty != a.specialty:
        out.append("특화: " + (", ".join(_l(t) for t in a.specialty) or "없음"))
    if b.require_tags != a.require_tags:
        out.append("필수: " + (", ".join(_l(t) for t in a.require_tags) or "없음"))
    if b.mode != a.mode:
        out.append(f"이동수단: {_l(a.mode) if a.mode else '미지정'}")
    if b.walk.option != a.walk.option:
        out.append(f"도보 옵션: {_l(a.walk.option)}")
    if b.walk.max_min != a.walk.max_min:
        out.append(f"도보 최대 {a.walk.max_min}분" if a.walk.max_min else "도보 시간 제한 해제")
    if b.walk.avoid != a.walk.avoid:
        out.append("피하기: " + (", ".join(_l(t) for t in a.walk.avoid) or "없음"))
    added = set(a.exclude_ids) - set(b.exclude_ids)
    if added:
        out.append(f"{len(added)}곳 제외")
    if set(a.pin_ids) - set(b.pin_ids):
        out.append("고정 추가")
    if b.sort != a.sort:
        out.append(f"정렬: {_l(a.sort)}")
    return out or ["변경 없음"]
