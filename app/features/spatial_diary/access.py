"""공간 일기 공개 표면의 인증 계약. 실제 인증 조립 전에는 fail closed다."""

from dataclasses import dataclass

from fastapi import HTTPException


@dataclass(frozen=True)
class SpatialDiaryPrincipal:
    """인증 계층이 주입하는 최소 권한 문맥. Profile source는 인증 근거가 아니다."""

    owner_id: str
    dog_ids: frozenset[str]


def get_spatial_diary_principal() -> SpatialDiaryPrincipal:
    """앱 조립부가 실제 인증 dependency로 override하기 전에는 공개 조회·쓰기를 닫는다."""

    raise HTTPException(503, "spatial diary authorization is not configured")


def require_dog_access(principal: SpatialDiaryPrincipal, dog_id: str) -> None:
    """다른 견주의 subject 존재 여부를 노출하지 않는다."""

    if dog_id not in principal.dog_ids:
        raise HTTPException(404, "spatial diary resource not found")
