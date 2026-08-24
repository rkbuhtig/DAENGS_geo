"""산책 기록 — 이 레포가 바깥에 **주는** 것. docs/contracts/walk-record.md

사실만 있다. 시간 · 거리 · 속도 · 정지 — 폰 GPS 가 ±2~5% 로 주는 것 (research/2026-08-19-walk-data-evidence.md).
목표 · 보상 · 점수 · 트리거 · 권유 · 서술은 **여기 없다.** 그건 이 모델을 소비하는 쪽의 일이고 전부 옵션이다.
사용자에게 보여줄 문장 필드도 없다 — 문자열은 식별자뿐이다.

필드 집합은 tests/test_walk_contract.py 가 고정한다. 하나 더하면 깨진다. 깨뜨리는 것이 보이는 결정이다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RECORD_VERSION = 2
CALCULATION_VERSION = 2

EvidenceOrigin = Literal["device", "mock", "mixed", "unknown"]
SessionState = Literal["open", "sealed", "derived", "purged"]


class ContractModel(BaseModel):
    """바깥과 주고받는 형태. 모르는 값은 조용히 버리지 않는다."""

    model_config = ConfigDict(extra="forbid")


def _tz_required(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("walk timestamps must include a timezone")
    return value


class WalkFix(ContractModel):
    """수신 원본 한 점. 앱이 배치로 올린다. 속도는 여기 없다 — 점 둘 사이에서 계산한다."""

    # 네트워크 재전송과 업로드 순서가 측정열을 바꾸지 않게 클라이언트가 부여한다.
    client_seq: int = Field(ge=0)
    at: datetime
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(None, ge=0)
    # 재생·가짜 위치 표식. Android 가 DEVICE/MOCK 을 가르는 것의 서버 짝 —
    # 개발 재생 세션이 진짜 산책 사실처럼 쌓이지 않게 한다. 판정 아님, 표식만.
    is_mock: bool = False

    _tz = field_validator("at")(_tz_required)


class WalkSession(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    dog_id: str = Field(min_length=1, max_length=128)
    started_at: datetime
    ended_at: datetime | None = None          # None = 진행 중
    fix_count: int = Field(0, ge=0)
    state: SessionState = "open"
    evidence_origin: EvidenceOrigin = "unknown"

    _tz = field_validator("started_at", "ended_at")(
        lambda v: v if v is None else _tz_required(v)
    )

    @model_validator(mode="after")
    def ends_after_start(self) -> "WalkSession":
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at must not precede started_at")
        return self


class WalkFacts(ContractModel):
    """세션이 끝난 뒤 코드가 계산한 사실. 바깥에 나가는 것은 이것이다."""

    record_version: Literal[RECORD_VERSION] = RECORD_VERSION
    calculation_version: int = Field(CALCULATION_VERSION, ge=1)
    session_id: str = Field(min_length=1, max_length=128)
    dog_id: str = Field(min_length=1, max_length=128)
    evidence_origin: EvidenceOrigin
    started_at: datetime
    ended_at: datetime

    duration_s: int = Field(ge=0)
    distance_m: int = Field(ge=0)             # 원 GPS 누적. 정지 중 지터 포함 — 참고값
    moving_distance_m: int = Field(ge=0)      # 속도 임계 이하 구간 0 처리. **거리는 이것이다**
    moving_s: int = Field(ge=0)
    stop_count: int = Field(ge=0)             # "정지"까지만. 냄새 맡기로 단정하지 않는다
    stop_s: int = Field(ge=0)
    avg_speed_mps: float | None = Field(None, ge=0)   # moving 기준. moving_s 가 0 이면 None
    fix_count: int = Field(ge=0)

    _tz = field_validator("started_at", "ended_at")(_tz_required)

    @model_validator(mode="after")
    def consistent(self) -> "WalkFacts":
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must not precede started_at")
        if self.moving_distance_m > self.distance_m:
            raise ValueError("moving_distance_m cannot exceed distance_m")
        if self.moving_s + self.stop_s > self.duration_s:
            raise ValueError("moving_s + stop_s cannot exceed duration_s")
        wall_s = round((self.ended_at - self.started_at).total_seconds())
        if self.duration_s > wall_s:
            raise ValueError("duration_s cannot exceed the session wall time")
        return self


class MotionEventOccurrence(ContractModel):
    """세션 안에서 관측된 상태 변화. 이유·장소 의미는 붙이지 않는다."""

    session_id: str = Field(min_length=1, max_length=128)
    event_index: int = Field(ge=0)
    type: Literal["stop"] = "stop"
    started_at: datetime
    ended_at: datetime
    duration_s: int = Field(ge=0)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    route_offset_m: float = Field(ge=0)
    accuracy_p50_m: float | None = Field(None, ge=0)
    fix_count: int = Field(ge=2)

    _tz = field_validator("started_at", "ended_at")(_tz_required)

    @model_validator(mode="after")
    def ends_after_start(self) -> "MotionEventOccurrence":
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must not precede started_at")
        return self
