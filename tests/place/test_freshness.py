"""파생값이 언제 낡았다고 말하는가 — 재파생 공통 규약.

Decision: #70

    fresh = (같은 규칙 버전) AND (같은 입력 지문)

버전만 보던 때는 재적재가 원문을 덮어써도 파생값이 안 따라왔다. 실증(2026-08-28):
`목줄` → `대형견 입장 불가` 로 바꾸고 배치를 돌리면 **0행**을 훑고 지나갔고, 그 행은
대형견 배제를 원문에 갖고도 `require:leash` 를 계속 내보냈다.
"""

from app.ingest.freshness import EMPTY_INPUT, fingerprint, is_stale

VERSION = "v1"


def test_same_input_gives_the_same_fingerprint():
    assert fingerprint("목줄") == fingerprint("목줄")


def test_different_input_gives_a_different_fingerprint():
    assert fingerprint("목줄") != fingerprint("대형견 입장 불가")


def test_missing_input_still_gets_a_fingerprint():
    """`None` 이 지문 NULL 이 되면 "아직 안 팠다" 와 구분이 안 되고 매번 다시 판다."""
    assert fingerprint(None)
    assert fingerprint(None) != fingerprint("")


def test_the_sentinel_is_storable_in_postgres_text():
    """NUL 을 쓰면 `md5(COALESCE(입력, :empty))` 가 통째로 죽는다."""
    assert "\x00" not in EMPTY_INPUT


def test_a_row_without_a_fingerprint_is_stale():
    """모르면 판다 — 0019 이전 행은 지문이 없다."""
    assert is_stale(
        stored_fp=None, current_fp=fingerprint("목줄"),
        stored_version=VERSION, current_version=VERSION,
    )


def test_a_changed_rule_is_stale():
    fp = fingerprint("목줄")
    assert is_stale(
        stored_fp=fp, current_fp=fp, stored_version="v1", current_version="v2",
    )


def test_a_changed_input_is_stale():
    """**이 축이 없던 것이 리뷰가 지적한 구조적 결함이다.**"""
    assert is_stale(
        stored_fp=fingerprint("목줄"), current_fp=fingerprint("대형견 입장 불가"),
        stored_version=VERSION, current_version=VERSION,
    )


def test_matching_rule_and_input_is_fresh():
    fp = fingerprint("목줄")
    assert not is_stale(
        stored_fp=fp, current_fp=fp, stored_version=VERSION, current_version=VERSION,
    )
