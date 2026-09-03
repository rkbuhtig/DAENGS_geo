package com.daengs.geo.map.shell

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.map.layers.places.PlaceMarkerState
import com.daengs.geo.map.layers.territory.TerritoryLayerState
import com.daengs.geo.map.layers.trail.TrailLayerState

/** Why the user is looking at the map. A purpose is exclusive; overlay toggles are not. */
enum class MapPurpose {
    PLACE_SEARCH,
    WALK,
    TERRITORY,
}

/** Provider-neutral intent for how much built-in map context should compete with app overlays. */
enum class BaseMapStyle {
    SEARCH_DETAIL,
    WALK_CONTEXT,
    TERRITORY_FOCUSED,
}

/** The only place where a map purpose becomes an allowed set of visible app layers. */
data class MapDisplayPolicy(
    val showPlaceResults: Boolean,
    val showTrail: Boolean,
    val showTerritory: Boolean,
    val baseMapStyle: BaseMapStyle,
)

fun mapDisplayPolicy(
    purpose: MapPurpose,
    trailPreferred: Boolean,
    walkActive: Boolean,
): MapDisplayPolicy =
    when (purpose) {
        MapPurpose.PLACE_SEARCH -> MapDisplayPolicy(
            showPlaceResults = true,
            showTrail = false,
            showTerritory = false,
            baseMapStyle = BaseMapStyle.SEARCH_DETAIL,
        )
        MapPurpose.WALK -> MapDisplayPolicy(
            showPlaceResults = false,
            showTrail = trailPreferred,
            showTerritory = false,
            baseMapStyle = BaseMapStyle.WALK_CONTEXT,
        )
        MapPurpose.TERRITORY -> MapDisplayPolicy(
            showPlaceResults = false,
            // An old walk must not become background decoration on the game board. During a live
            // walk the muted trail remains useful context for where the player just came from.
            showTrail = trailPreferred && walkActive,
            showTerritory = true,
            baseMapStyle = BaseMapStyle.TERRITORY_FOCUSED,
        )
    }

/** Candidate layers before visibility policy is applied. Features own these values, not the map. */
data class MapSceneSources(
    val currentPosition: GeoPoint? = null,
    val places: List<PlaceMarkerState> = emptyList(),
    val trail: TrailLayerState = TrailLayerState(),
    val territory: TerritoryLayerState = TerritoryLayerState(),
)

/**
 * Applies policy before values reach a provider renderer. Hidden means an empty layer, so a
 * provider cannot accidentally draw stale facilities or territory by ignoring a visibility flag.
 */
fun composeMapScene(
    policy: MapDisplayPolicy,
    sources: MapSceneSources,
): MapScene = MapScene(
    currentPosition = sources.currentPosition,
    places = sources.places.takeIf { policy.showPlaceResults }.orEmpty(),
    trail = sources.trail.takeIf { policy.showTrail } ?: TrailLayerState(),
    territory = sources.territory.takeIf { policy.showTerritory } ?: TerritoryLayerState(),
    baseMapStyle = policy.baseMapStyle,
)
