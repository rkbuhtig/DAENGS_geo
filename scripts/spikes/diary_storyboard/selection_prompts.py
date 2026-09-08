"""Opt-in selection instructions; existing v1 stage prompts remain unchanged."""

SELECT = """전체 산책 자료를 이해하고 시간순 장면 개요를 선택한다. 본문은 아직 쓰지 않는다.
evidence_snapshot.context.candidate_catalog가 사건 범위와 선택 정책의 원본이다.
카드 자격이 없는 연결 구간은 connection 이유로 생략하고 required 후보는 보존한다.
모든 후보를 selection.decisions에 정확히 한 번 기록한다. 선택은 code=selected와 scene_id,
생략은 scene_id=null과 실제 이유 코드/설명을 반환한다. 후보 하나에 장면 하나만 연결한다.
장면 수가 max_scenes보다 적으면 budget 때문에 생략했다고 하지 않는다.
장면 수를 채우지 않는다. 남길 이유가 없으면 outline=[]도 정상이다.
선택한 사건의 시작/끝 시각을 그대로 유지한다. point 사건은 시작과 끝이 같다.
각 장면은 해당 후보의 중심 근거를 포함하고 다른 후보의 근거를 가져오지 않는다.
title_draft는 선택한 내용에 근거한 제목과 evidence_ids다. 빈 구성에서는 null을 허용한다.
이해는 잠정적이다. 구조 검사 통과가 서술의 사실성 보장은 아니다.
"""

COMPOSE = """전체 산책을 이해하고 사건들을 사용자에게 읽힐 장면으로 구성한다. 본문은 아직 쓰지 않는다.
원본은 evidence_snapshot.context.candidate_catalog다. 관측 사건과 장면은 다른 단위다.
selection.compositions에 장면마다 중심 사건 primary_candidate_id, 포함 사건 included_candidate_ids,
맥락 사건 context_candidate_ids, 따로 읽거나 함께 묶었을 때 무엇을 전달하는지 reason을 기록한다.
중심 사건은 포함 사건 중 하나다. 포함 사건은 하나의 장면만 소유하며 맥락은 다른 장면에서도 참조 가능하다.
required 사건은 반드시 포함 사건으로 남긴다. 맥락에만 숨기지 않는다. 행동마다 별도 카드는 필요 없다.
연결 이동은 맥락으로만 사용 가능하다. 다른 GPS chain이나 공백을 가로질러 묶지 않는다.
모든 후보를 decisions에 한 번씩 기록한다. 포함은 selected와 소유 scene_id, 맥락 전용은 context와
scene_id=null, 나머지는 실제 생략 이유다. context_scene_ids에는 맥락으로 참조한 모든 장면을 적는다.
개요 시작/끝은 대표 사건의 원래 시각만 사용한다. 여러 사건 범위를 행동 지속시간으로 합치지 않는다.
개요 evidence_ids에는 모든 포함 사건의 중심 근거를 남긴다. 근거는 해당 구성의 사건 안에서만 고른다.
장면은 대표 사건 시간순으로 정렬한다. max_scenes는 카드 상한이지 포함할 사건 수 상한이 아니다.
상한보다 적게 만들고 budget을 생략 이유로 사용하지 않는다. 장면 수를 채우지 않으며 빈 구성도 허용한다.
title_draft는 선택한 내용에 근거한 초안이다. 구성 이유·잠정 이해가 원본 관측이 되지는 않는다.
"""

COMPOSE_WRITE = """이 실행은 여러 사건을 하나의 장면으로 편집하는 구성이다.
board_before.selection.compositions 및 제공된 scene_context의 원본 사건별 시각·근거를 유지한다.
outline 시각은 대표 사건의 시각이며 장면 안의 모든 행동의 지속시간이 아니다.
포함 사건의 중심 근거를 모두 주장 목록에 남기고 원본 기록은 읽을 수 있게 보존한다.
맥락은 행동의 원인·동기·지속시간이 아니다. 다른 장면에 같은 맥락이 있어도 별도 행동 발생으로 세지 않는다.
재검토는 문구를 바꿀 수 있지만 구성과 대표 사건은 이 비교 실행에서 고정한다.
"""


def selection_instructions(catalog):
    if catalog.composition_mode == "grouped":
        return {"compose": COMPOSE, "write": COMPOSE_WRITE}
    return SELECT
