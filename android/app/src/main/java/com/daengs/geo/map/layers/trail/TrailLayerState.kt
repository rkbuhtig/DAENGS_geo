package com.daengs.geo.map.layers.trail

import com.daengs.geo.location.GeoPoint

/**
 * One path per recorded segment. Hiding the layer means handing over no paths, so a renderer
 * cannot draw a hidden layer by forgetting a visibility flag.
 */
data class TrailLayerState(
    val paths: List<List<GeoPoint>> = emptyList(),
)
