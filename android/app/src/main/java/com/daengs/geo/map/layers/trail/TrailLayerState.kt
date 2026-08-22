package com.daengs.geo.map.layers.trail

import com.daengs.geo.location.GeoPoint

data class TrailLayerState(
    val points: List<GeoPoint> = emptyList(),
    val visible: Boolean = true,
)
