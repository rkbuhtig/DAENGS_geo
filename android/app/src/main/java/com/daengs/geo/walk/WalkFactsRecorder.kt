package com.daengs.geo.walk

import com.daengs.geo.location.LocationSample
import com.daengs.geo.location.distanceToMeters
import kotlin.math.roundToInt
import kotlin.math.roundToLong

enum class WalkFactSource { DEVICE, MOCK, MIXED }

enum class WalkFactQuality { GOOD, LIMITED, INSUFFICIENT }

data class WalkFactsPreview(
    val calculationVersion: Int,
    val startedAtMillis: Long,
    val endedAtMillis: Long,
    /** Sum of recorded segment time. Pauses and feed-switch gaps are deliberately excluded. */
    val durationSeconds: Long,
    val distanceMeters: Int,
    val movingDistanceMeters: Int,
    val movingSeconds: Long,
    val stopCount: Int,
    val stopSeconds: Long,
    val averageSpeedMetersPerSecond: Double?,
    val fixCount: Int,
    val segmentCount: Int,
    val droppedLowAccuracy: Int,
    val source: WalkFactSource,
    val quality: WalkFactQuality,
)

data class WalkCalculationPolicy(
    val version: Int = 1,
    val minDistanceMeters: Double = 3.0,
    val movingSpeedMetersPerSecond: Double = 0.5,
    val minStopDurationMillis: Long = 10_000,
    val maxAccuracyMeters: Float = 50f,
    val maxJumpMeters: Double = 200.0,
    val maxSamples: Int = 20_000,
) {
    init {
        require(version > 0)
        require(minDistanceMeters >= 0)
        require(movingSpeedMetersPerSecond >= 0)
        require(minStopDurationMillis >= 0)
        require(maxAccuracyMeters >= 0)
        require(maxJumpMeters > 0)
        require(maxSamples > 0)
    }
}

/**
 * Records fact inputs independently from the map trail.
 *
 * TrailRecorder intentionally drops stationary jitter because it draws a line. Stop time needs
 * those samples, so deriving facts from the rendered trail would manufacture movement. This
 * recorder receives the same LocationSample stream but keeps the observation boundary intact.
 */
class WalkFactsRecorder(
    private val policy: WalkCalculationPolicy = WalkCalculationPolicy(),
) {
    private enum class State { OFF, RECORDING, PAUSED }

    private var state = State.OFF
    private var segments = mutableListOf<MutableList<LocationSample>>()
    private var breakBeforeNext = false
    private var droppedLowAccuracy = 0
    private var unknownAccuracy = 0
    private var droppedAtCapacity = 0
    private var acceptedSampleCount = 0

    fun start() {
        state = State.RECORDING
        segments = mutableListOf()
        breakBeforeNext = false
        droppedLowAccuracy = 0
        unknownAccuracy = 0
        droppedAtCapacity = 0
        acceptedSampleCount = 0
    }

    fun pause() {
        if (state == State.RECORDING) {
            state = State.PAUSED
            breakBeforeNext = true
        }
    }

    fun resume() {
        if (state == State.PAUSED) {
            state = State.RECORDING
            breakBeforeNext = true
        }
    }

    fun stop(): WalkFactsPreview? {
        state = State.OFF
        return calculate()
    }

    /** Feed changes create a new fact segment so mock and device time are never joined. */
    fun breakSegment() {
        breakBeforeNext = true
    }

    fun add(sample: LocationSample) {
        if (state != State.RECORDING) return
        val accuracy = sample.accuracyMeters
        if (accuracy == null) {
            unknownAccuracy++
        } else if (accuracy > policy.maxAccuracyMeters) {
            droppedLowAccuracy++
            return
        }
        if (acceptedSampleCount >= policy.maxSamples) {
            droppedAtCapacity++
            return
        }

        val previous = segments.lastOrNull()?.lastOrNull()
        val jumpMeters = previous?.point?.distanceToMeters(sample.point) ?: 0.0
        val startsSegment = previous == null || breakBeforeNext || jumpMeters > policy.maxJumpMeters
        if (startsSegment) {
            segments += mutableListOf(sample)
        } else {
            segments.last() += sample
        }
        acceptedSampleCount++
        breakBeforeNext = false
    }

    private fun calculate(): WalkFactsPreview? {
        val samples = segments.flatten()
        if (samples.isEmpty()) return null

        var durationMillis = 0L
        var distanceMeters = 0.0
        var movingDistanceMeters = 0.0
        var movingMillis = 0L
        var stopMillis = 0L
        var stopCount = 0
        var invalidIntervals = 0

        segments.forEach { segment ->
            var stopRunMillis = 0L

            fun flushStopRun() {
                if (stopRunMillis >= policy.minStopDurationMillis) {
                    stopCount++
                    stopMillis += stopRunMillis
                }
                stopRunMillis = 0
            }

            segment.zipWithNext().forEach { (before, after) ->
                val intervalMillis = intervalMillis(before, after)
                if (intervalMillis <= 0) {
                    invalidIntervals++
                    flushStopRun()
                    return@forEach
                }
                val rawDistance = before.point.distanceToMeters(after.point)
                val filteredDistance = if (rawDistance >= policy.minDistanceMeters) rawDistance else 0.0
                val speed = filteredDistance / (intervalMillis / 1_000.0)

                durationMillis += intervalMillis
                distanceMeters += filteredDistance
                if (speed >= policy.movingSpeedMetersPerSecond) {
                    flushStopRun()
                    movingMillis += intervalMillis
                    movingDistanceMeters += filteredDistance
                } else {
                    stopRunMillis += intervalMillis
                }
            }
            flushStopRun()
        }

        val source = sourceOf(samples)
        val quality = when {
            samples.size < 2 || durationMillis <= 0 -> WalkFactQuality.INSUFFICIENT
            droppedLowAccuracy > 0 || unknownAccuracy > 0 || droppedAtCapacity > 0 ||
                invalidIntervals > 0 -> WalkFactQuality.LIMITED
            else -> WalkFactQuality.GOOD
        }
        return WalkFactsPreview(
            calculationVersion = policy.version,
            startedAtMillis = samples.first().capturedAtMillis,
            endedAtMillis = samples.last().capturedAtMillis,
            durationSeconds = millisecondsToSeconds(durationMillis),
            distanceMeters = distanceMeters.roundToInt(),
            movingDistanceMeters = movingDistanceMeters.roundToInt(),
            movingSeconds = millisecondsToSeconds(movingMillis),
            stopCount = stopCount,
            stopSeconds = millisecondsToSeconds(stopMillis),
            averageSpeedMetersPerSecond = if (movingMillis > 0) {
                movingDistanceMeters / (movingMillis / 1_000.0)
            } else {
                null
            },
            fixCount = samples.size,
            segmentCount = segments.size,
            droppedLowAccuracy = droppedLowAccuracy,
            source = source,
            quality = quality,
        )
    }

    private fun intervalMillis(before: LocationSample, after: LocationSample): Long {
        val beforeElapsed = before.elapsedRealtimeNanos
        val afterElapsed = after.elapsedRealtimeNanos
        if (beforeElapsed != null && afterElapsed != null) {
            return (afterElapsed - beforeElapsed) / NANOS_PER_MILLISECOND
        }
        return after.capturedAtMillis - before.capturedAtMillis
    }

    private fun sourceOf(samples: List<LocationSample>): WalkFactSource {
        val hasMock = samples.any { it.isMock }
        val hasDevice = samples.any { !it.isMock }
        return when {
            hasMock && hasDevice -> WalkFactSource.MIXED
            hasMock -> WalkFactSource.MOCK
            else -> WalkFactSource.DEVICE
        }
    }

    private fun millisecondsToSeconds(value: Long): Long = (value / 1_000.0).roundToLong()

    private companion object {
        const val NANOS_PER_MILLISECOND = 1_000_000L
    }
}
