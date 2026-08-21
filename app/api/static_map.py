"""정적 지도 프록시. 제공사 키를 클라이언트에 노출하지 않기 위해 서버가 대신 받아온다."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response

from app.providers.base import LatLng, MapMarker, StaticMapSpec
from app.providers.naver import NaverProvider
from app.providers.registry import static_map_provider

router = APIRouter(prefix="/map", tags=["map"])


@router.get("/static")
async def static_map(
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    zoom: Annotated[int, Query(ge=1, le=20)] = 16,
    w: Annotated[int, Query(ge=1, le=1024)] = 600,
    h: Annotated[int, Query(ge=1, le=1024)] = 300,
    m: Annotated[str, Query(max_length=4000)] = "",
):
    markers = []
    try:
        items = list(filter(None, m.split(",")))
        if len(items) > 100:
            raise ValueError("at most 100 markers are allowed")
        for item in items:
            mlat, mlng, label, hl = item.split(":")
            marker_lat, marker_lng = float(mlat), float(mlng)
            if not (-90 <= marker_lat <= 90 and -180 <= marker_lng <= 180):
                raise ValueError("marker coordinates out of range")
            if len(label) > 20 or hl not in ("0", "1"):
                raise ValueError("invalid marker label or highlight")
            markers.append(MapMarker(LatLng(marker_lat, marker_lng), label, hl == "1"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid markers: {exc}") from exc
    spec = StaticMapSpec(LatLng(lat, lng), zoom, w, h, tuple(markers))
    provider = static_map_provider()

    if isinstance(provider, NaverProvider):
        return Response(await provider.fetch_static_png(spec), media_type="image/png")
    raise HTTPException(404, "static map provider not configured")
