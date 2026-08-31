from scripts.source_fact_coverage import summarize_kto


def test_coverage_keeps_missing_detail_unknown():
    summary = summarize_kto(
        [
            (
                {
                    "contenttypeid": "12",
                    "lclsSystm1": "NA",
                    "lclsSystm2": "NA01",
                    "lclsSystm3": "NA010100",
                },
                {},
            ),
            (
                {"contenttypeid": "39"},
                {
                    "acmpyTypeCd": "일부구역 동반가능",
                    "acmpyNeedMtr": "목줄 착용",
                },
            ),
        ]
    )

    assert summary["rows"] == 2
    assert summary["detail_rows"] == 1
    assert summary["scope_evidence_state"] == {"unknown": 1, "known": 1}
    assert summary["predicate_code"] == {"require:leash": 1}
