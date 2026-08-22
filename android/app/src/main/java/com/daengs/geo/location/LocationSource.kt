package com.daengs.geo.location

import kotlinx.coroutines.flow.Flow

data class GeoPoint(
    val latitude: Double,
    val longitude: Double,
)

data class LocationSample(
    val point: GeoPoint,
    val capturedAtMillis: Long,
    val elapsedRealtimeNanos: Long? = null,
    val accuracyMeters: Float? = null,
    val speedMetersPerSecond: Float? = null,
    val isMock: Boolean = false,
)

data class LocationUpdateConfig(
    val intervalMillis: Long = 1_500,
    val minIntervalMillis: Long = 750,
    val minDistanceMeters: Float = 1f,
)

interface LocationSource {
    suspend fun currentLocation(): LocationSample

    fun locationUpdates(config: LocationUpdateConfig = LocationUpdateConfig()): Flow<LocationSample>
}
