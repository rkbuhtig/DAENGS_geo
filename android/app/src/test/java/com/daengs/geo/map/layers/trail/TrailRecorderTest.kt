package com.daengs.geo.map.layers.trail

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.location.LocationSample
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TrailRecorderTest {
    @Test
    fun `pausing splits the trail and the gap is not walked distance`() {
        val recorder = TrailRecorder(minDistanceMeters = 1.0)
        val first = sample(37.0, 127.0, 1L)
        val duringPause = sample(37.0001, 127.0, 2L)
        val afterResume = sample(37.0002, 127.0, 3L)

        recorder.start()
        recorder.add(first)
        recorder.pause()
        recorder.add(duringPause)
        assertEquals(listOf(listOf(first)), recorder.snapshot().segments)

        recorder.resume()
        val snapshot = recorder.add(afterResume)

        assertEquals(listOf(listOf(first), listOf(afterResume)), snapshot.segments)
        assertEquals(0.0, snapshot.distanceMeters, 0.001)
    }

    @Test
    fun `walking within a segment accumulates distance`() {
        val recorder = TrailRecorder(minDistanceMeters = 1.0)
        recorder.start()
        recorder.add(sample(37.0, 127.0, 1L))

        val snapshot = recorder.add(sample(37.0002, 127.0, 2L))

        assertEquals(1, snapshot.segments.size)
        assertTrue(snapshot.distanceMeters > 20.0)
    }

    @Test
    fun `an implausible jump starts a new segment without counting the gap`() {
        val recorder = TrailRecorder(minDistanceMeters = 1.0, maxJumpMeters = 200.0)
        recorder.start()
        recorder.add(sample(37.5665, 126.9780, 1L))

        val snapshot = recorder.add(sample(35.1796, 129.0756, 2L))

        assertEquals(2, snapshot.segments.size)
        assertEquals(0.0, snapshot.distanceMeters, 0.001)
    }

    @Test
    fun `a feed switch breaks the segment so mock and real fixes are not stitched`() {
        val recorder = TrailRecorder(minDistanceMeters = 1.0)
        recorder.start()
        recorder.add(sample(37.0, 127.0, 1L))

        recorder.breakSegment()
        val snapshot = recorder.add(sample(37.0002, 127.0, 2L))

        assertEquals(2, snapshot.segments.size)
        assertEquals(0.0, snapshot.distanceMeters, 0.001)
    }

    @Test
    fun `bad accuracy and jitter are ignored and low accuracy is counted`() {
        val recorder = TrailRecorder(minDistanceMeters = 3.0, maxAccuracyMeters = 20f)
        recorder.start()
        recorder.add(sample(37.0, 127.0, 1L, accuracy = 5f))
        recorder.add(sample(37.000001, 127.0, 2L, accuracy = 5f))
        val snapshot = recorder.add(sample(37.001, 127.0, 3L, accuracy = 100f))

        assertEquals(1, snapshot.sampleCount)
        assertEquals(1, snapshot.skippedLowAccuracy)
    }

    @Test
    fun `an accepted fix clears the low accuracy streak`() {
        val recorder = TrailRecorder(minDistanceMeters = 1.0, maxAccuracyMeters = 20f)
        recorder.start()
        recorder.add(sample(37.0, 127.0, 1L, accuracy = 500f))
        assertEquals(1, recorder.snapshot().skippedLowAccuracy)

        val snapshot = recorder.add(sample(37.0, 127.0, 2L, accuracy = 5f))

        assertEquals(0, snapshot.skippedLowAccuracy)
    }

    private fun sample(
        latitude: Double,
        longitude: Double,
        time: Long,
        accuracy: Float = 5f,
    ) = LocationSample(
        point = GeoPoint(latitude, longitude),
        capturedAtMillis = time,
        accuracyMeters = accuracy,
    )
}
