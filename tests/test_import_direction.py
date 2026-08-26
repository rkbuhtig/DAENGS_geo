"""패키지 사이 import 가 결정 #67 의 방향을 지키는가.

**왜 필요한가**: 이 규칙은 지금까지 사람이 grep 으로 지켰다. 그렇게 지키면 다음에 기능을
급히 넣는 사람이 `geo` 에서 `features` 를 하나 부르는 순간 조용히 무너지고, 되돌리려면
그 위에 쌓인 것까지 같이 건드려야 한다. 다섯 개 PR 로 끊어낸 순환이 한 줄로 돌아온다.

## 규칙

    응용 → 도메인 → 인프라 → core        층 사이는 한 방향
    역방향은 선언된 계약 모듈로만          (§3)
    같은 층 안은 DAG                      순환 금지, 방향은 자유
    계약 모듈은 core 와 계약만 import      로직을 담지 않는다

## 알려진 위반을 0 으로 요구하지 않는 이유

`KNOWN_VIOLATIONS` 는 **정확히 일치**해야 한다 — 하나라도 늘면 실패하고, 고쳤는데 여기서
안 지워도 실패한다. 위반이 0 이 될 때까지 이 테스트를 미루면 그때까지 아무것도 안 지켜진다.
목록이 있으면 지금 있는 부채는 그대로 두고 **새 부채만 막는다.** 목록이 저절로 줄지 않는
것이 요점이다 — 고친 사람이 여기서 지우면서 부채가 사라진 것을 기록하게 된다.
"""

import ast
import collections
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parent.parent / "app"

# 결정 #67 §1. 새 최상위 패키지는 여기 등록되지 않으면 테스트가 막는다 (§5).
LAYERS = {
    "core": 0,
    "providers": 1, "usage": 1,
    "profile": 2, "geo": 2, "discovery": 2, "place": 2, "journey": 2,
    "api": 3, "features": 3, "ingest": 3,
}
LAYER_NAMES = {0: "core", 1: "인프라", 2: "도메인", 3: "응용"}

# 결정 #67 §3. 파일명 패턴이 아니라 이 집합이 기준이다 — `providers/base.py` 는
# 이름이 contract 가 아니지만 제공사 계약을 소유한 기존 계약 모듈이다.
CONTRACT_MODULES = {
    "profile.contract",
    "providers.base",
    "geo.contract",
    "journey.contract",
}

# 정확히 일치해야 한다. 위 docstring 참고.
#
# geo/paint.py · geo/region.py 가 features.walk.facts.Segment 를 가져간다. Segment 를
# geo 로 내리는 것은 답이 아니다 — WalkFix · moving · chain_index 를 품고 있어 walk 어휘가
# 통째로 따라온다. region.py 가 자기 docstring 에서 "features/walk/encounter.py 의 면
# 버전"이라고 선언하고 두 파일의 소비자가 전부 walk 쪽이라, paint/region 의 소유권을
# 다시 보는 쪽이 맞다. 붓 실험이 끝난 뒤에 판단한다.
KNOWN_VIOLATIONS = {
    ("geo.paint", "features"),
    ("geo.region", "features"),
}


def _packages() -> set[str]:
    return {p.name for p in _APP.iterdir() if p.is_dir() and (p / "__init__.py").exists()}


def _edges() -> list[tuple[str, str, str, str]]:
    """(출발 패키지, 출발 모듈경로, 도착 패키지, 도착 모듈) 목록.

    **패키지 내부 import 도 담는다.** 계약 모듈이 자기 패키지의 로직을 부르는 것이 §3 이
    금지하는 것 중 하나인데, 내부를 버리면 그게 안 보인다. 층 검사 쪽에서 `src != tgt` 로
    거른다.
    """
    pkgs = _packages()
    out = []
    for path in sorted(_APP.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(_APP).parts
        if not rel or rel[0] not in pkgs:
            continue
        src = rel[0]
        src_mod = ".".join(rel).removesuffix(".py").removesuffix(".__init__")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
                continue
            if not node.module.startswith("app."):
                continue
            parts = node.module.split(".")
            tgt = parts[1]
            tgt_mod = ".".join(parts[1:])
            if tgt in pkgs:
                out.append((src, src_mod, tgt, tgt_mod))
    return out


# ------------------------------------------------------------------ 양성 대조
# 발견이 깨지면 아래 규칙 테스트가 0건을 훑고 조용히 통과한다. tests/test_script_imports.py
# 가 같은 이유로 같은 방어를 한다.
def test_discovery_actually_finds_the_app():
    pkgs = _packages()
    assert len(pkgs) >= 10, pkgs
    assert {"core", "geo", "discovery", "features", "journey"} <= pkgs
    assert len(_edges()) >= 50, len(_edges())


def test_every_package_has_a_layer():
    """새 최상위 패키지는 층을 배정받아야 한다 — 결정 #67 §5 의 기계적 집행."""
    unassigned = sorted(_packages() - set(LAYERS))
    assert not unassigned, (
        f"층이 없는 최상위 패키지: {unassigned}. 결정 #67 §1 의 네 축 중 하나에 속함을 "
        "결정 문서로 증명하고 LAYERS 에 등록하라."
    )


def test_contract_modules_exist():
    """선언만 하고 파일이 없으면 §3 검사가 아무것도 안 지킨다."""
    for mod in sorted(CONTRACT_MODULES):
        assert (_APP / Path(*mod.split("."))).with_suffix(".py").exists(), mod


# ------------------------------------------------------------------ 규칙
def test_layer_direction():
    """층 사이는 한 방향. 역방향은 선언된 계약 모듈로만."""
    found = set()
    for src, src_mod, tgt, tgt_mod in _edges():
        if src == tgt:
            continue
        if LAYERS[tgt] <= LAYERS[src] or tgt_mod in CONTRACT_MODULES:
            continue
        found.add((src_mod, tgt))

    new = found - KNOWN_VIOLATIONS
    fixed = KNOWN_VIOLATIONS - found
    assert not new, (
        "새 역방향 import: "
        + ", ".join(f"{s}({LAYER_NAMES[LAYERS[s.split('.')[0]]]}) → {t}({LAYER_NAMES[LAYERS[t]]})"
                    for s, t in sorted(new))
        + ". 계약이면 CONTRACT_MODULES 에, 아니면 소유권을 다시 보라 (결정 #67 §2·§3)."
    )
    assert not fixed, (
        f"고쳐진 위반이 KNOWN_VIOLATIONS 에 남아 있다: {sorted(fixed)}. "
        "목록에서 지워라 — 남겨두면 다음 사람이 아직 부채라고 읽는다."
    )


def test_no_cycles_within_a_layer():
    """같은 층 안은 방향이 자유롭지만 순환은 안 된다 (features 형제끼리 포함)."""
    intra = collections.defaultdict(set)
    for src, _, tgt, _ in _edges():
        if src != tgt and LAYERS[src] == LAYERS[tgt]:
            intra[src].add(tgt)
    pairs = sorted({tuple(sorted((a, b))) for a in intra for b in intra[a] if a in intra.get(b, ())})
    assert not pairs, f"같은 층 안 양방향 참조: {pairs}"


@pytest.mark.parametrize("contract", sorted(CONTRACT_MODULES))
def test_contract_modules_are_leaves(contract: str):
    """계약 모듈은 core 와 다른 계약만 안다. 로직이 섞이면 여기서 걸린다."""
    for _, src_mod, tgt, tgt_mod in _edges():
        if src_mod != contract:
            continue
        assert LAYERS[tgt] == 0 or tgt_mod in CONTRACT_MODULES, (
            f"{contract} 가 {tgt_mod} 를 import 한다. 계약 모듈은 core 와 다른 계약만 안다 (§3). "
            "같은 패키지의 로직도 마찬가지다 — 계약이 로직을 알면 그건 계약이 아니다."
        )
