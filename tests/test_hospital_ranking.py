"""`POST /hospital/search` 의 순위 계약. 부품이 아니라 **요청 하나가 통과하는 길**을 본다.

**왜 필요한가**: `find_places` 도 `_sort` 도 각자 멀쩡했는데, 그 사이에서 evidence 가
boost 에 섞이면서 순위가 state 밖의 값에 흔들렸다. 함수별 테스트 97개가 전부 통과했다.
계약은 함수가 아니라 요청 단위로 써야 잡힌다.

계약: **state 가 같으면 결과 순서도 같다.** 무상태 서버(클라가 state 를 되돌려준다)의
전제이고, 이게 깨지면 사용자는 조건을 안 건드렸는데 목록이 재배열되는 걸 본다.

단언은 **심은 행만 추려서** 한다. TEST_ORIGIN 반경 안에 공공데이터 실행이 들어와 있어
(울릉도) 전체 목록으로 비교하면 적재 상태에 따라 테스트가 흔들린다. 상대 순서만 보면
남의 행이 사이에 끼어도 계약은 그대로 검증된다.
"""

import pytest

from app.core.config import settings
from app.features.hospital.api import HospitalSearchIn, hospital_search
from app.planning.state import EditableState
from tests.conftest import TEST_ORIGIN, place_row, seeded_places

# 같은 500m 밴드 안의 두 곳. 밴드가 같아야 boost 가 순서를 뒤집을 수 있어서 —
# 밴드가 다르면 거리가 이기므로 이 회귀를 아예 못 본다.
# "논현동물의료센터"는 FakeCommunitySearch 시드 스니펫 2개에 이름이 박혀 있다
# (enrich/community.py `_SEED`) → 예전 계산식이면 boost=+2 를 받아 더 가까운 곳을 제쳤다.
NEAR, FAR = "가까운동물병원", "논현동물의료센터"
ROWS = [
    place_row("r1", NEAR, east_m=200),        # 더 가깝다. 근거 없음
    place_row("r2", FAR, east_m=400),         # 더 멀다. 근거 2개가 붙는다
]

# 규칙에 하나도 안 걸리는 발화 → FakeLLM 이 ask 만 낸다 → **state 는 그대로**.
# 그런데 예전엔 이것만으로 want_ev 가 켜져서 순위가 바뀌었다.
NO_OP_UTTERANCE = "음 글쎄요"


@pytest.fixture
def fake_community(monkeypatch):
    """가짜 근거는 이제 기본값이 아니다 (운영 순위를 흔들어서). 근거 계약을 보는 테스트만 켠다."""
    monkeypatch.setattr(settings, "community_provider", "fake")
    monkeypatch.setattr(settings, "dev_console", True)


def _state() -> EditableState:
    return EditableState(lat=TEST_ORIGIN[0], lng=TEST_ORIGIN[1])


async def _search(db, state: EditableState | None = None, **kw):
    transport = kw.pop("transport", "none")
    return await hospital_search(
        HospitalSearchIn(state=state or _state(), transport=transport, **kw), db,
    )


def _ours(out, names: tuple[str, ...]) -> list[str]:
    """심은 행만 원래 순서대로. 반경 안 실데이터는 계약과 무관하다."""
    return [r.name for r in out.results if r.name in names]


async def test_utterance_presence_does_not_reorder_results():
    """같은 state, 발화만 있고 없고 → 순서가 같아야 한다.

    발화는 state 를 바꾸지 않는다(ask). 그러니 순서가 달라지면 그건 state 밖의
    일회성 값이 순위에 들어갔다는 뜻이다.
    """
    async with seeded_places(ROWS) as db:
        quiet = _ours(await _search(db), (NEAR, FAR))
        spoken = _ours(await _search(db, utterance=NO_OP_UTTERANCE), (NEAR, FAR))
    assert quiet == spoken == [NEAR, FAR]


async def test_evidence_boosts_when_the_state_says_so(fake_community):
    """근거가 과목 신호의 본체다 — 단, **state 가 시킬 때만** (query-rewrite-experiment.md).

    증상이 state 에 있으면: 쿼리 재작성 → 스니펫 → 병원명 매칭 → 같은 밴드 안에서 앞선다.
    증상이 없으면: 근거 조회 자체가 없고, 순위는 거리순 그대로다.
    utterance 는 어느 쪽에도 못 낀다 — 그게 1번에서 잡은 버그다.
    """
    async with seeded_places(ROWS) as db:
        plain = await _search(db)
        st = _state()
        st.target.symptoms = ["숨을 헐떡"]        # FakeCommunitySearch 시드가 논현동물의료센터를 문다
        sympt = await _search(db, state=st)

    assert _ours(plain, (NEAR, FAR)) == [NEAR, FAR], "증상 없으면 거리순"
    hit = next(r for r in plain.results if r.name == FAR)
    assert not hit.evidence, "state 가 안 시켰는데 근거를 조회했다"

    assert _ours(sympt, (NEAR, FAR)) == [FAR, NEAR], "매칭된 근거가 같은 밴드 안에서 앞서야 한다"
    hit = next(r for r in sympt.results if r.name == FAR)
    assert hit.evidence and hit.boost >= len(hit.evidence)


async def test_same_state_same_evidence_regardless_of_utterance(fake_community):
    """증상이 state 에 있으면, 그 턴에 말을 했든 안 했든 근거·순위가 같다."""
    async with seeded_places(ROWS) as db:
        st = _state(); st.target.symptoms = ["숨을 헐떡"]
        quiet = await _search(db, state=st.model_copy(deep=True))
        spoken = await _search(db, state=st.model_copy(deep=True), utterance=NO_OP_UTTERANCE)
    assert _ours(quiet, (NEAR, FAR)) == _ours(spoken, (NEAR, FAR))
    q = next(r for r in quiet.results if r.name == FAR)
    s = next(r for r in spoken.results if r.name == FAR)
    assert q.boost == s.boost and len(q.evidence) == len(s.evidence)


async def test_specialty_still_boosts_within_band():
    """부스트 자체는 살아 있다 — 사용자가 요청한 특화만."""
    ortho = "정형잘보는동물병원"
    rows = [place_row("r1", NEAR, east_m=200),
            place_row("r2", ortho, east_m=400, tags=["ortho"])]
    async with seeded_places(rows) as db:
        st = _state()
        st.target.specialty = ["ortho"]
        out = await _search(db, state=st)
    assert _ours(out, (NEAR, ortho)) == [ortho, NEAR]


async def test_hospital_request_uses_resolved_journey_and_view_plans():
    """state를 API가 직접 주워 쓰지 않고 resolver 결정이 응답까지 관통한다."""
    async with seeded_places(ROWS) as db:
        state = _state()
        state.urgency = "urgent"
        state.journey.preferred_mode = "walk"
        out = await _search(db, state=state, transport="estimate")

    assert out.show_call_cta is True
    assert out.call_reasons == ["user"]
    assert out.results
    assert all(r.transport.mode_priority[0] == "car" for r in out.results if r.transport)
    overridden = {entry.overrode for entry in out.resolution if entry.overrode}
    assert {"journey.preferred_mode", "sort"} <= overridden
