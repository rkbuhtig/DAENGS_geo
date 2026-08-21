package com.daengs.geo.location

data class GeoPoint(
    val latitude: Double,
    val longitude: Double,
)

fun interface LocationSource {
    suspend fun currentLocation(): GeoPoint
}
