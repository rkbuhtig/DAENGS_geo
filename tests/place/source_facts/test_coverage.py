from app.place.source_facts.states import DetailAcquisitionState
from scripts.source_fact_coverage import summarize_kcisa, summarize_kto


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
                DetailAcquisitionState.UNKNOWN,
            ),
            (
                {"contenttypeid": "39"},
                {
                    "acmpyTypeCd": "일부구역 동반가능",
                    "acmpyNeedMtr": "목줄 착용",
                },
                DetailAcquisitionState.FETCHED,
            ),
        ]
    )

    assert summary["rows"] == 2
    assert summary["detail_rows"] == 1
    assert summary["scope_evidence_state"] == {"unknown": 1, "known": 1}
    assert summary["predicate_code"] == {"require:leash": 1}


def test_kcisa_coverage_keeps_physical_count_and_missing_product_visible():
    row = {
        "시설명": "불허미술관",
        "카테고리1": "반려동물업",
        "카테고리2": "반려동반여행",
        "카테고리3": "미술관",
        "반려동물 동반 가능정보": "N",
        "장소(실내) 여부": "N",
        "장소(실외)여부": "N",
    }

    summary = summarize_kcisa([(row, 3, "ref", None)])

    assert summary["distinct_records"] == 1
    assert summary["physical_rows"] == 3
    assert summary["allowed"] == {"False": 1}
    assert summary["dual_read"]["missing_facility"] == 1
