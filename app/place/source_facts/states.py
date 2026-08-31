"""값과 독립적인 원천 사실 상태."""

from enum import StrEnum


class FactState(StrEnum):
    """`false` 같은 값과 그 값을 얻은 상태를 섞지 않는다."""

    KNOWN = "known"
    NOT_PROVIDED = "not_provided"
    NOT_FETCHED = "not_fetched"
    NOT_APPLICABLE = "not_applicable"
    PARSE_FAILED = "parse_failed"
    UNKNOWN = "unknown"


class EvidenceCertainty(StrEnum):
    """원천의 직접 진술인지, 결정론적 해석인지."""

    SOURCE = "source"
    DERIVED = "derived"


class ProjectionState(StrEnum):
    """레코드 전체 projection의 상태. 개별 사실 상태와 별개다."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
