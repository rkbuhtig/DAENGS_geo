"""에뮬레이터 검증이 device evidence를 만들지 않는 마지막 게이트."""

from scripts.verify.walk_emulator_drive import mock_fix_summary


def test_mock_fix_summary_requires_explicit_true_values():
    assert mock_fix_summary({"fixes": [{"is_mock": True}, {"is_mock": True}]}) == (2, 2)
    assert mock_fix_summary({"fixes": [{"is_mock": True}, {"is_mock": False}, {}]}) == (1, 3)
