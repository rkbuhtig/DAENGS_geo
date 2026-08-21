"""refine: (state | None, edits, utterance) → (new state, changes, question?)

순서: 초안 생성(프로필 기본값) → UI edits 적용 → utterance를 LLM이 툴로 → 적용 → diff.
"""

from dataclasses import dataclass, field

from app.planning.state import EditableState
from app.profile.contract import DogProfile
from app.refine import tools
from app.refine.diff import changes as diff_changes
from app.refine.diff import changes_by_policy
from app.refine.nl import ToolCall, llm


@dataclass
class RefineResult:
    state: EditableState
    changes: list[str]
    grouped: dict[str, list[str]] = field(default_factory=dict)   # 정책별 (target/journey/view)
    applied: list[ToolCall] = field(default_factory=list)
    question: str | None = None


def draft(lat: float, lng: float, profile: DogProfile | None, radius_m: int) -> EditableState:
    """초안. 필터 없음. 프로필은 도보 옵션 '기본값'에만 — 사용자가 끄면 꺼진다."""
    s = EditableState(lat=lat, lng=lng)
    s.target.radius_m = radius_m
    if profile and (profile.is_senior or profile.has_joint_issue):
        s.journey.walk.option = "no_stairs"      # journey 기본값만. 결과를 거르지 않는다
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


async def refine(state: EditableState | None, edits: list[ToolCall], utterance: str | None,
                 shown_ids: list[int], profile: DogProfile | None,
                 lat: float, lng: float, default_radius: int) -> RefineResult:
    if state is None:
        base = draft(lat, lng, profile, default_radius)
    else:
        # origin은 매 요청의 현재 위치다. 클라이언트 state보다 새 요청 값을 우선한다.
        # history에는 넣지 않는다 — GPS 갱신은 사용자가 undo할 조건 편집이 아니다.
        base = state.model_copy(deep=True)
        base.lat, base.lng = lat, lng
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

    grouped = changes_by_policy(base, cur)
    ch = diff_changes(base, cur)
    if state is None:
        ch = diff_changes(None, base) + ([] if ch == ["변경 없음"] else ch)
        grouped["target"] = changes_by_policy(None, base)["target"] + grouped["target"]
    return RefineResult(state=cur, changes=ch, grouped=grouped, applied=applied, question=question)
