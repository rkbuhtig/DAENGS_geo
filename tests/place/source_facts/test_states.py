from app.place.source_facts.contract import FactEvidence
from app.place.source_facts.states import FactState


def test_boolean_value_and_fact_state_are_independent():
    evidence = FactEvidence(
        state=FactState.KNOWN,
        source_field="주차 가능여부",
        raw_value="N",
        parser_version="test/1",
    )
    assert evidence.state is FactState.KNOWN
    assert evidence.raw_value == "N"


def test_not_fetched_is_not_the_same_as_unknown():
    assert FactState.NOT_FETCHED != FactState.UNKNOWN
