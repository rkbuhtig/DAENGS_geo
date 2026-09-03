"""중립 점령지 읽기. 앱용 주변 조회와 dev 검수 조회가 저장소만 공유한다."""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.territory.game.contract import TerritorySite

_NEARBY = text("""
WITH origin AS (
    SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography AS point
)
SELECT site_id,
       ST_Y(location::geometry) AS lat,
       ST_X(location::geometry) AS lng,
       ST_Distance(location, origin.point) AS distance_m
FROM territory_site
CROSS JOIN origin
WHERE ST_DWithin(location, origin.point, :radius_m)
ORDER BY location <-> origin.point, site_id
LIMIT :limit
""")

_INSPECT = text("""
SELECT site_id, source, kind,
       ST_Y(location::geometry) AS lat,
       ST_X(location::geometry) AS lng,
       instt, as_of
FROM territory_site
WHERE location && ST_MakeEnvelope(:west, :south, :east, :north, 4326)::geography
  AND (CAST(:kind AS text) IS NULL OR kind = :kind)
ORDER BY site_id
LIMIT :limit
""")


@dataclass(frozen=True)
class TerritorySiteInspection:
    """적재 결과를 사람이 검수할 때만 쓰는 원천 정보."""

    site_id: str
    source: str
    kind: str
    lat: float
    lng: float
    instt: str | None
    as_of: str | None


async def find_nearby(
    db: AsyncSession,
    *,
    lat: float,
    lng: float,
    radius_m: float,
    limit: int,
) -> tuple[tuple[TerritorySite, ...], bool]:
    """위치 주변을 거리순으로 읽는다. `radius_m`은 선로딩 범위이지 점령 반경이 아니다."""
    rows = (
        await db.execute(
            _NEARBY,
            {"lat": lat, "lng": lng, "radius_m": radius_m, "limit": limit + 1},
        )
    ).all()
    truncated = len(rows) > limit
    return (
        tuple(
            TerritorySite(
                site_id=row.site_id,
                lat=row.lat,
                lng=row.lng,
                distance_m=row.distance_m,
            )
            for row in rows[:limit]
        ),
        truncated,
    )


async def inspect_bbox(
    db: AsyncSession,
    *,
    south: float,
    west: float,
    north: float,
    east: float,
    kind: str | None,
    limit: int,
) -> tuple[tuple[TerritorySiteInspection, ...], bool]:
    """dev 지도에서 적재 밀도와 원천을 검수한다. 앱 계약으로 내보내지 않는다."""
    rows = (
        await db.execute(
            _INSPECT,
            {
                "south": south,
                "west": west,
                "north": north,
                "east": east,
                "kind": kind,
                "limit": limit + 1,
            },
        )
    ).all()
    truncated = len(rows) > limit
    return (
        tuple(
            TerritorySiteInspection(
                site_id=row.site_id,
                source=row.source,
                kind=row.kind,
                lat=row.lat,
                lng=row.lng,
                instt=row.instt,
                as_of=row.as_of.isoformat() if row.as_of is not None else None,
            )
            for row in rows[:limit]
        ),
        truncated,
    )
