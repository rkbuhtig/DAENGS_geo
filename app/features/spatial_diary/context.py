"""동결 TrailContext 원자를 현재 공간 일기 facet으로 분류하는 공용 정책."""

from app.features.spatial_diary.contract import ContextStatus, TrailContextSnapshot

CONTEXT_POLICY_VERSION = 1
DIARY_CALENDAR_TIMEZONE = "Asia/Seoul"
RAIN_THRESHOLD_MM = 0.1
FACET_VALUES = {
    "precipitation": frozenset({"rain", "dry", "unknown"}),
    "daylight": frozenset({"day", "night", "unknown"}),
}


def context_facets(snapshot: TrailContextSnapshot) -> dict[str, str]:
    """없는 원자는 반대 상태로 채우지 않고 unknown으로 남긴다."""

    observed = snapshot.status in {ContextStatus.CAPTURED, ContextStatus.PARTIAL}
    if not observed:
        return {"precipitation": "unknown", "daylight": "unknown"}
    precipitation = (
        "unknown"
        if snapshot.precipitation_mm is None
        else "rain"
        if snapshot.precipitation_mm >= RAIN_THRESHOLD_MM
        else "dry"
    )
    daylight = (
        "unknown"
        if snapshot.sun_elevation_deg is None
        else "day"
        if snapshot.sun_elevation_deg >= 0
        else "night"
    )
    return {"precipitation": precipitation, "daylight": daylight}
