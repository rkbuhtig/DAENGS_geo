package com.daengs.geo.map.layers.places

import com.daengs.geo.location.GeoPoint

data class PlaceMarkerState(
    val id: String,
    val point: GeoPoint,
    val label: String,
    val selected: Boolean = false,
)
