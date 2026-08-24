package com.daengs.geo.walk

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.location.LocationSample
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

enum class TrackingState { OFF, RECORDING, PAUSED }

/**
 * The trail is a list of segments, not one flat point list. A pause or an implausible jump ends
 * the current segment: the gap is neither drawn as a line nor counted as walked distance.
 */
data class TrailSnapshot(
    val state: TrackingState = TrackingState.OFF,
    val segments: List<List<LocationSample>> = emptyList(),
    val distanceMeters: Double = 0.0,
    /** Consecutive fixes dropped for poor accuracy. Non-zero means recording looks stuck. */
    val skippedLowAccuracy: Int = 0,
) {
    val sampleCount: Int get() = segments.sumOf { it.size }

    val lastSample: LocationSample? get() = segments.lastOrNull()?.lastOrNull()
}

class TrailRecorder(
    private val minDistanceMeters: Double = 3.0,
    private val maxAccuracyMeters: Float = 50f,
    private val maxJumpMeters: Double = 200.0,
    private val maxSamples: Int = 5_000,
) {
    private var snapshot = TrailSnapshot()
    private var breakBeforeNext = false

    fun snapshot(): TrailSnapshot = snapshot

    fun start(): TrailSnapshot {
        breakBeforeNext = false
        snapshot = TrailSnapshot(state = TrackingState.RECORDING)
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
            breakBeforeNext = true
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
        if (sample.accuracyMeters != null && sample.accuracyMeters > maxAccuracyMeters) {
            snapshot = snapshot.copy(skippedLowAccuracy = snapshot.skippedLowAccuracy + 1)
            return snapshot
        }

        val previous = snapshot.lastSample
        val delta = previous?.point?.distanceTo(sample.point) ?: 0.0
        if (previous != null && !breakBeforeNext && delta < minDistanceMeters) {
            snapshot = snapshot.copy(skippedLowAccuracy = 0)
            return snapshot
        }

        val startsSegment = previous == null || breakBeforeNext || delta > maxJumpMeters
        breakBeforeNext = false
        val segments = if (startsSegment) {
            snapshot.segments + listOf(listOf(sample))
        } else {
            snapshot.segments.dropLast(1) + listOf(snapshot.segments.last() + sample)
        }
        snapshot = snapshot.copy(
            segments = trim(segments),
            distanceMeters = snapshot.distanceMeters + if (startsSegment) 0.0 else delta,
            skippedLowAccuracy = 0,
        )
        return snapshot
    }

    private fun trim(segments: List<List<LocationSample>>): List<List<LocationSample>> {
        var excess = segments.sumOf { it.size } - maxSamples
        if (excess <= 0) return segments
        val kept = mutableListOf<List<LocationSample>>()
        for (segment in segments) {
            when {
                excess <= 0 -> kept += segment
                excess >= segment.size -> excess -= segment.size
                else -> {
                    kept += segment.drop(excess)
                    excess = 0
                }
            }
        }
        return kept
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
