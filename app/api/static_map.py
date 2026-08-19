"""정적 지도 프록시. 제공사 키를 클라이언트에 노출하지 않기 위해 서버가 대신 받아온다."""

from fastapi import APIRouter, HTTPException, Response

from app.providers.base import LatLng, MapMarker, StaticMapSpec
from app.providers.naver import NaverProvider
from app.providers.registry import static_map_provider

router = APIRouter(prefix="/map", tags=["map"])


@router.get("/static")
async def static_map(lat: float, lng: float, zoom: int = 16, w: int = 600, h: int = 300, m: str = ""):
    provider = static_map_provider()
    markers = []
    for item in filter(None, m.split(",")):
        mlat, mlng, label, hl = item.split(":")
        markers.append(MapMarker(LatLng(float(mlat), float(mlng)), label, hl == "1"))
    spec = StaticMapSpec(LatLng(lat, lng), zoom, w, h, tuple(markers))

    if isinstance(provider, NaverProvider):
        return Response(await provider.fetch_static_png(spec), media_type="image/png")
    raise HTTPException(404, "static map provider not configured")
