package com.daengs.geo.location

import kotlin.math.cos
import kotlin.math.roundToLong
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow

class ReplayLocationSource(
    private val points: List<GeoPoint>,
    private val speedMultiplier: Double = 1.0,
    private val walkingSpeedMetersPerSecond: Double = 1.3,
    private val sleeper: suspend (Long) -> Unit = { delay(it) },
    private val nowMillis: () -> Long = System::currentTimeMillis,
    private val elapsedRealtimeNanos: () -> Long = System::nanoTime,
    private val segmentDurationMillis: (GeoPoint, GeoPoint) -> Long = { from, to ->
        ((from.distanceToMeters(to) / walkingSpeedMetersPerSecond) * 1_000).roundToLong()
            .coerceAtLeast(1)
    },
) : LocationSource {
    init {
        require(points.isNotEmpty()) { "재생 경로에는 좌표가 하나 이상 필요합니다." }
        require(speedMultiplier > 0) { "재생 속도는 0보다 커야 합니다." }
        require(walkingSpeedMetersPerSecond > 0) { "가상 보행 속도는 0보다 커야 합니다." }
    }

    override suspend fun currentLocation(): LocationSample = sample(
        point = points.first(),
        capturedAtMillis = nowMillis(),
        elapsedRealtimeNanos = elapsedRealtimeNanos(),
    )

    override fun locationUpdates(config: LocationUpdateConfig): Flow<LocationSample> = flow {
        var simulatedAtMillis = nowMillis()
        var simulatedElapsedNanos = elapsedRealtimeNanos()
        points.forEachIndexed { index, point ->
            if (index > 0) {
                val simulatedDurationMillis = segmentDurationMillis(points[index - 1], point)
                sleeper((simulatedDurationMillis / speedMultiplier).roundToLong().coerceAtLeast(1))
                simulatedAtMillis += simulatedDurationMillis
                simulatedElapsedNanos += simulatedDurationMillis * NANOS_PER_MILLISECOND
            }
            emit(sample(point, simulatedAtMillis, simulatedElapsedNanos))
        }
    }

    private fun sample(
        point: GeoPoint,
        capturedAtMillis: Long,
        elapsedRealtimeNanos: Long,
    ) = LocationSample(
        point = point,
        capturedAtMillis = capturedAtMillis,
        elapsedRealtimeNanos = elapsedRealtimeNanos,
        accuracyMeters = 4f,
        speedMetersPerSecond = walkingSpeedMetersPerSecond.toFloat(),
        isMock = true,
    )

    companion object {
        private const val NANOS_PER_MILLISECOND = 1_000_000L

        /** A short loop anchored at the current point, suitable for emulator playback. */
        fun loopAround(origin: GeoPoint): List<GeoPoint> {
            val offsetsMeters = listOf(
                0.0 to 0.0,
                18.0 to 0.0,
                36.0 to 6.0,
                52.0 to 18.0,
                58.0 to 38.0,
                50.0 to 58.0,
                30.0 to 68.0,
                8.0 to 66.0,
                -10.0 to 50.0,
                -16.0 to 28.0,
                -10.0 to 8.0,
                0.0 to 0.0,
            )
            return offsetsMeters.map { (east, north) -> origin.offsetMeters(east, north) }
        }
    }
}

private fun GeoPoint.offsetMeters(east: Double, north: Double): GeoPoint {
    val latitudeDelta = north / 111_320.0
    val longitudeScale = 111_320.0 * cos(Math.toRadians(latitude)).coerceAtLeast(0.01)
    return GeoPoint(
        latitude = latitude + latitudeDelta,
        longitude = longitude + east / longitudeScale,
    )
}
