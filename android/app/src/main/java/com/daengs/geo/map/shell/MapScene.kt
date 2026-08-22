package com.daengs.geo.map.shell

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.map.layers.places.PlaceMarkerState
import com.daengs.geo.map.layers.territory.TerritoryLayerState
import com.daengs.geo.map.layers.trail.TrailLayerState

/**
 * Everything the map surface draws, already resolved by the shell. [currentPosition] is whatever
 * the live feed reports — during replay that is a fabricated point, which is why the hospital
 * search reads MapUiState.deviceLocation instead of anything in here.
 */
data class MapScene(
    val currentPosition: GeoPoint? = null,
    val places: List<PlaceMarkerState> = emptyList(),
    val trail: TrailLayerState = TrailLayerState(),
    val territory: TerritoryLayerState = TerritoryLayerState(),
)
