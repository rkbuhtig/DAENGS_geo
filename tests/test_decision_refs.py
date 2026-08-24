"""테스트가 인용한 `Decision: #N` 이 실재하는지 지킨다.

**왜 필요한가**: 결정 번호를 손으로 적으면 틀린다. 틀린 번호는 없는 번호보다 나쁘다 —
다음 사람과 에이전트가 **엉뚱한 결정을 근거로 삼고** 멀쩡한 테스트를 지우거나, 죽은
계약을 살아 있다고 믿는다. 규율로 막지 말고 여기서 막는다.

규칙은 "모든 테스트에 결정을 달아라"가 아니다. **"달았으면 실재해야 한다"** 이다.
정책·제품 결정에서 직접 파생된 테스트에만 붙인다.
"""

import re
from pathlib import Path

TESTS_DIR = Path(__file__).parent
DECISIONS_MD = TESTS_DIR.parent / "docs" / "decisions" / "README.md"

# 표의 첫 칸이 결정 번호다: `| 37 | **undo 의 단위는...` .
_DECISION_ROW = re.compile(r"^\|\s*(\d+)\s*\|", re.MULTILINE)
# 인용 형식: `Decision: #35` 또는 `Decision: #35, #18`
_CITATION = re.compile(r"Decision:\s*((?:#\d+\s*,?\s*)+)")
_NUMBER = re.compile(r"#(\d+)")


def known_decisions() -> set[int]:
    return {int(n) for n in _DECISION_ROW.findall(DECISIONS_MD.read_text(encoding="utf-8"))}


def citations() -> list[tuple[Path, int]]:
    """이 파일 자신은 제외한다.

    형식을 설명하려면 여기에 예시(`Decision: #35`)를 적어야 하는데, 그걸 세면 **다른
    테스트의 인용이 전부 사라져도 가드가 통과한다.** 자기 자신으로 만족하는 검사는
    검사가 아니다.
    """
    found: list[tuple[Path, int]] = []
    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        if path.resolve() == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8")
        for block in _CITATION.findall(text):
            found += [(path, int(n)) for n in _NUMBER.findall(block)]
    return found


def test_cited_decisions_exist():
    known = known_decisions()
    assert known, f"결정 표를 못 읽었다: {DECISIONS_MD}"

    missing = sorted({
        (path.relative_to(TESTS_DIR).as_posix(), number)
        for path, number in citations()
        if number not in known
    })

    assert not missing, (
        "실재하지 않는 결정을 인용한다. 번호를 고치거나 결정 문서에 추가하라:\n"
        + "\n".join(f"  {path} → #{number}" for path, number in missing)
    )


def test_the_convention_is_still_in_use():
    """인용이 0건이면 형식이 바뀌었거나 규칙이 조용히 사라진 것이다 — 위 검사가 무력해진다."""
    assert citations(), "Decision: #N 인용이 하나도 없다. 형식이 바뀌었는지 확인하라"
