"""refine: (state | None, edits, utterance) → (new state, changes, question?)

순서: 초안 생성(프로필 기본값) → UI edits 적용 → utterance를 LLM이 툴로 → 적용 → diff.
"""

from dataclasses import dataclass, field

from app.profile.contract import DogProfile
from app.refine import tools
from app.refine.diff import changes as diff_changes
from app.refine.nl import ToolCall, llm
from app.refine.state import SearchState


@dataclass
class RefineResult:
    state: SearchState
    changes: list[str]
    applied: list[ToolCall] = field(default_factory=list)
    question: str | None = None


def draft(lat: float, lng: float, profile: DogProfile | None, radius_m: int) -> SearchState:
    """초안. 필터 없음. 프로필은 도보 옵션 '기본값'에만 — 사용자가 끄면 꺼진다."""
    s = SearchState(lat=lat, lng=lng, radius_m=radius_m)
    if profile and (profile.is_senior or profile.has_joint_issue):
        s.walk.option = "no_stairs"
    return s


def profile_hint(p: DogProfile | None) -> str:
    if not p:
        return "없음"
    bits = [f"{p.name}", f"{p.age_years}세", p.size_class]
    if p.is_senior: bits.append("노령")
    if p.has_joint_issue: bits.append("관절")
    if p.is_brachy: bits.append("단두종")
    if p.has_car is False: bits.append("차 없음")
    return ", ".join(bits)


async def refine(state: SearchState | None, edits: list[ToolCall], utterance: str | None,
                 shown_ids: list[int], profile: DogProfile | None,
                 lat: float, lng: float, default_radius: int) -> RefineResult:
    base = state or draft(lat, lng, profile, default_radius)
    cur = base
    applied: list[ToolCall] = []
    question = None

    for e in edits:
        cur = tools.apply(cur, e.tool, e.args)
        applied.append(e)

    if utterance and utterance.strip():
        plan = await llm().plan(utterance, cur, shown_ids, profile_hint(profile))
        for c in plan:
            if c.tool == "ask":
                question = c.args.get("question")
                continue
            cur = tools.apply(cur, c.tool, c.args)
            applied.append(c)

    ch = diff_changes(base, cur)
    if state is None:
        ch = diff_changes(None, base) + ([] if ch == ["변경 없음"] else ch)
    return RefineResult(state=cur, changes=ch, applied=applied, question=question)
