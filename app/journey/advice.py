"""도보 판정 — 개 계수, 옵션 선택, advice 규칙. companion=dog일 때만 의미 있다.

재료가 있는 것만 판단한다 (docs/research 조합표). 개 밀도·그늘·인도 폭·경사는 재료가 없어 여기 없다.
"""

from app.profile.contract import DogProfile
from app.providers.base import Facilities, RouteResult, WalkOption


def _topic(name: str) -> str:
    """한국어 주격 조사: 받침 있으면 '은', 없으면 '는'."""
    if not name:
        return ""
    ch = name[-1]
    if "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28:
        return name + "은"
    return name + "는"


OPTION_LABEL = {"recommended": "골목 섞인 추천", "main_road": "큰길 위주", "shortest": "최단", "no_stairs": "계단 제외"}


def dog_time_factor(profile: DogProfile | None) -> float:
    """제공사 도보 시간은 성인 4.4km/h(TMAP 실측). 개 데리고는 느리다."""
    if not profile:
        return 1.2                     # 기본: 냄새 맡기·배변
    f = 1.2
    if profile.is_senior: f += 0.3
    if profile.has_joint_issue: f += 0.2
    if profile.is_brachy: f += 0.2
    if profile.size_class == "small": f += 0.1
    if profile.activity_level == "high": f -= 0.1
    return round(min(f, 2.0), 2)


def prefers_quiet(profile: DogProfile | None) -> bool:
    return bool(profile and ({"reactive_to_dogs", "timid"} & set(profile.temperament)))


def walk_options_to_try(prefer: WalkOption, avoid: list[str], profile: DogProfile | None,
                        is_night: bool = False) -> list[WalkOption]:
    """실측 시 몇 개 옵션을 받아 비교할지.

    계단제외(30)는 실측상 거의 차이가 없어 기본 비교축에서 뺐다. 대신 **골목 섞인 추천(0) vs 큰길 위주(4)** —
    성격(반응성·겁)이면 골목, 밤이면 큰길. 이게 매번 발동하는 진짜 선택지.
    """
    opts: list[WalkOption] = [prefer]
    if "recommended" not in opts:          # 골목 섞인 추천은 항상 기준선
        opts.append("recommended")
    if "main_road" not in opts and (prefers_quiet(profile) or is_night):
        opts.append("main_road")
    if "stairs" in avoid and "no_stairs" not in opts:
        opts.append("no_stairs")
    return opts


def choose_walk(walks: list[RouteResult], prefer: WalkOption, avoid: list[str],
                profile: DogProfile | None, factor: float, is_night: bool) -> tuple[RouteResult, list[str]]:
    """옵션 비교. 반환: (선택, 이유들). 시설 페널티 + 시간 + 길 성격(성격/밤)."""
    quiet = prefers_quiet(profile)

    def score(r: RouteResult) -> float:
        fac = r.facilities or Facilities()
        s = fac.penalty(tuple(avoid)) + r.duration_s * factor / 60 / 5
        ratio = fac.big_road_ratio
        if quiet:            # 큰길 많을수록 불리
            s += ratio * 4
        if is_night:         # 밤엔 큰길 많을수록 유리
            s -= ratio * 3
        if r.option == prefer:
            s -= 0.5
        return s

    best = min(walks, key=score)
    why: list[str] = []
    if len(walks) > 1:
        # 이유는 '고른 옵션' 기준으로만 말한다. 비율은 근거 숫자로 따로 나간다 (road_mix)
        if best.option == "main_road" and is_night:
            why.append("밤이라 밝은 큰길 위주로")
        elif best.option == "main_road" and quiet:
            why.append("큰길 위주가 오히려 마주침 적음(이 구간)")
        elif best.option in ("recommended", "no_stairs") and quiet:
            why.append(f"{_topic(profile.name)} 개·소음 반응이 있어 골목 섞인 길로")
    return best, why


def walk_advice(r: RouteResult, profile: DogProfile | None, max_min: int | None,
                avoid: list[str], temp_c: float | None = None,
                factor: float = 1.0) -> tuple[str, list[str]]:
    why: list[str] = []
    level = 0  # 0 ok, 1 caution, 2 avoid
    minutes = r.duration_s * factor / 60
    fac = r.facilities or Facilities()

    if max_min is not None and minutes > max_min:
        level = 2; why.append(f"{int(minutes)}분 > 제한 {max_min}분")

    if profile:
        cap = 45.0
        if profile.is_senior: cap = 20.0
        if profile.has_joint_issue: cap = min(cap, 15.0)
        if profile.is_brachy: cap = min(cap, 20.0)
        if profile.size_class == "small" and profile.weight_kg < 4: cap = min(cap, 20.0)
        if minutes > cap * 1.5:
            level = 2; why.append(f"{int(minutes)}분 — {profile.name}에겐 과함(권장 ≤{int(cap)}분)")
        elif minutes > cap:
            level = max(level, 1); why.append(f"{int(minutes)}분 — 권장 {int(cap)}분 초과")
        if fac.stairs and (profile.is_senior or profile.has_joint_issue):
            # 사유는 실제로 해당하는 것만 — 어린 관절 이슈 개에게 '노령'이라고 하면 안 된다 (뽀글)
            reason = " · ".join(r for r, on in (("노령", profile.is_senior), ("관절", profile.has_joint_issue)) if on)
            level = 2; why.append(f"계단 {fac.stairs}회 — {reason}")
        if fac.underpass and profile.size_class == "large":
            level = max(level, 1); why.append(f"지하 통로 {fac.underpass}곳({fac.underpass_m}m) — 대형견 스트레스")
        if profile.is_brachy and temp_c is not None and temp_c >= 28:
            level = 2; why.append(f"단두종 + {temp_c:.0f}℃")
        if prefers_quiet(profile) and fac.big_crossings >= 3:
            level = max(level, 1); why.append(f"큰길 횡단 {fac.big_crossings}회 — 마주침 주의")

    for a in avoid:
        n = getattr(fac, a, 0)
        if n:
            level = max(level, 1)
            why.append({"stairs": "계단", "underpass": "지하 통로", "overpass": "육교"}.get(a, a) + f" {n} (피하기 요청)")
    if fac.crosswalk >= 6:
        level = max(level, 1); why.append(f"횡단보도 {fac.crosswalk}회")

    return ("ok", "caution", "avoid")[level], why
