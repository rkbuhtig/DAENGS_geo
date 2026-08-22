package com.daengs.geo.map.shell

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.map.layers.places.PlaceMarkerState
import com.daengs.geo.map.layers.territory.TerritoryLayerState
import com.daengs.geo.map.layers.trail.TrailLayerState

data class MapScene(
    val deviceLocation: GeoPoint? = null,
    val places: List<PlaceMarkerState> = emptyList(),
    val trail: TrailLayerState = TrailLayerState(),
    val territory: TerritoryLayerState = TerritoryLayerState(),
)
