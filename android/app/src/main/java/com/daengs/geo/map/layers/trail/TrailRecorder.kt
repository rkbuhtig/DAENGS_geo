package com.daengs.geo.map.layers.trail

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.location.LocationSample
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

enum class TrackingState { OFF, RECORDING, PAUSED }

data class TrailSnapshot(
    val state: TrackingState = TrackingState.OFF,
    val samples: List<LocationSample> = emptyList(),
    val distanceMeters: Double = 0.0,
)

class TrailRecorder(
    private val minDistanceMeters: Double = 3.0,
    private val maxAccuracyMeters: Float = 50f,
    private val maxSamples: Int = 5_000,
) {
    private var snapshot = TrailSnapshot()

    fun snapshot(): TrailSnapshot = snapshot

    fun start(clearPrevious: Boolean = true): TrailSnapshot {
        snapshot = if (clearPrevious) {
            TrailSnapshot(state = TrackingState.RECORDING)
        } else {
            snapshot.copy(state = TrackingState.RECORDING)
        }
        return snapshot
    }

    fun pause(): TrailSnapshot {
        if (snapshot.state == TrackingState.RECORDING) {
            snapshot = snapshot.copy(state = TrackingState.PAUSED)
        }
        return snapshot
    }

    fun resume(): TrailSnapshot {
        if (snapshot.state == TrackingState.PAUSED) {
            snapshot = snapshot.copy(state = TrackingState.RECORDING)
        }
        return snapshot
    }

    fun stop(): TrailSnapshot {
        snapshot = snapshot.copy(state = TrackingState.OFF)
        return snapshot
    }

    fun add(sample: LocationSample): TrailSnapshot {
        if (snapshot.state != TrackingState.RECORDING) return snapshot
        if (sample.accuracyMeters != null && sample.accuracyMeters > maxAccuracyMeters) return snapshot

        val previous = snapshot.samples.lastOrNull()
        val delta = previous?.point?.distanceTo(sample.point) ?: 0.0
        if (previous != null && delta < minDistanceMeters) return snapshot

        val updated = (snapshot.samples + sample).takeLast(maxSamples)
        snapshot = snapshot.copy(
            samples = updated,
            distanceMeters = snapshot.distanceMeters + delta,
        )
        return snapshot
    }
}

internal fun GeoPoint.distanceTo(other: GeoPoint): Double {
    val earthRadiusMeters = 6_371_000.0
    val lat1 = Math.toRadians(latitude)
    val lat2 = Math.toRadians(other.latitude)
    val latDelta = lat2 - lat1
    val lngDelta = Math.toRadians(other.longitude - longitude)
    val a = sin(latDelta / 2) * sin(latDelta / 2) +
        cos(lat1) * cos(lat2) * sin(lngDelta / 2) * sin(lngDelta / 2)
    return 2 * earthRadiusMeters * atan2(sqrt(a), sqrt(1 - a))
}
