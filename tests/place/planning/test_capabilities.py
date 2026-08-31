from app.place.contracts import PlaceResult
from app.place.planning.capabilities import CAPABILITIES
from app.place.planning.execution import EXECUTORS
from app.place.source_facts.contract import SourceFactProjection


def _model_path_exists(model, path: str) -> bool:
    section, field = path.split(".", maxsplit=1)
    section_model = model.model_fields[section].annotation
    return field in section_model.model_fields


def test_every_declared_capability_has_a_fact_path_and_executor() -> None:
    assert len({spec.capability_id for spec in CAPABILITIES}) == len(CAPABILITIES)
    assert {spec.executor_id for spec in CAPABILITIES} == set(EXECUTORS)
    assert all(
        _model_path_exists(SourceFactProjection, path)
        for spec in CAPABILITIES
        for path in spec.projection_paths
    )
    assert all(
        _model_path_exists(PlaceResult, path)
        for spec in CAPABILITIES
        for path in spec.execution_paths
    )


def test_capability_metadata_does_not_pretend_static_coverage_is_current_data() -> None:
    for spec in CAPABILITIES:
        dumped = spec.model_dump()
        assert "coverage" not in dumped
        assert "freshness" not in dumped
        assert "raw_fields" not in dumped
