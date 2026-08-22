package com.daengs.geo.map.layers.trail

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.location.LocationSample
import com.daengs.geo.location.distanceToMeters

enum class TrackingState { OFF, RECORDING, PAUSED }

/**
 * The trail is a list of segments, not one flat point list. A pause, a feed switch or an
 * implausible jump ends the current segment: the gap is neither drawn as a line nor counted
 * as walked distance, because the dog did not walk it.
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

    /** The next accepted fix starts a new segment. Used when the location feed changes. */
    fun breakSegment() {
        breakBeforeNext = true
    }

    fun add(sample: LocationSample): TrailSnapshot {
        if (snapshot.state != TrackingState.RECORDING) return snapshot
        if (sample.accuracyMeters != null && sample.accuracyMeters > maxAccuracyMeters) {
            snapshot = snapshot.copy(skippedLowAccuracy = snapshot.skippedLowAccuracy + 1)
            return snapshot
        }

        val previous = snapshot.lastSample
        val delta = previous?.point?.distanceToMeters(sample.point) ?: 0.0
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
