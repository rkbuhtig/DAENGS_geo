package com.daengs.geo.walk

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.location.LocationSample
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WalkFactsRecorderTest {
    @Test
    fun `moving samples become versioned facts`() {
        val recorder = WalkFactsRecorder()
        recorder.start()
        recorder.add(sample(37.0, 0, isMock = true))
        recorder.add(sample(37.000117, 10_000, isMock = true))
        recorder.add(sample(37.000234, 20_000, isMock = true))

        val facts = requireNotNull(recorder.stop())

        assertEquals(1, facts.calculationVersion)
        assertEquals(20, facts.durationSeconds)
        assertEquals(26, facts.distanceMeters)
        assertEquals(26, facts.movingDistanceMeters)
        assertEquals(20, facts.movingSeconds)
        assertEquals(0, facts.stopCount)
        assertEquals(0, facts.stopSeconds)
        assertEquals(3, facts.fixCount)
        assertEquals(1, facts.segmentCount)
        assertEquals(WalkFactSource.MOCK, facts.source)
        assertEquals(WalkFactQuality.GOOD, facts.quality)
        assertTrue(requireNotNull(facts.averageSpeedMetersPerSecond) in 1.2..1.4)
    }

    @Test
    fun `stationary observations are retained as a stop instead of disappearing from the trail`() {
        val recorder = WalkFactsRecorder()
        recorder.start()
        recorder.add(sample(37.0, 0))
        recorder.add(sample(37.0, 5_000))
        recorder.add(sample(37.0, 15_000))

        val facts = requireNotNull(recorder.stop())

        assertEquals(15, facts.durationSeconds)
        assertEquals(0, facts.distanceMeters)
        assertEquals(0, facts.movingSeconds)
        assertEquals(1, facts.stopCount)
        assertEquals(15, facts.stopSeconds)
        assertNull(facts.averageSpeedMetersPerSecond)
    }

    @Test
    fun `raw distance preserves stationary jitter while moving distance filters it`() {
        val recorder = WalkFactsRecorder()
        recorder.start()
        recorder.add(sample(37.0, 0))
        recorder.add(sample(37.00001, 5_000))
        recorder.add(sample(37.00002, 15_000))

        val facts = requireNotNull(recorder.stop())

        assertEquals(2, facts.distanceMeters)
        assertEquals(0, facts.movingDistanceMeters)
        assertEquals(0, facts.movingSeconds)
        assertEquals(1, facts.stopCount)
        assertEquals(15, facts.stopSeconds)
    }

    @Test
    fun `pause and resume exclude the gap and start a new fact segment`() {
        val recorder = WalkFactsRecorder()
        recorder.start()
        recorder.add(sample(37.0, 0))
        recorder.add(sample(37.000117, 10_000))
        recorder.pause()
        recorder.resume()
        recorder.add(sample(37.001, 1_000_000))
        recorder.add(sample(37.001117, 1_010_000))

        val facts = requireNotNull(recorder.stop())

        assertEquals(20, facts.durationSeconds)
        assertEquals(26, facts.distanceMeters)
        assertEquals(2, facts.segmentCount)
    }

    @Test
    fun `feed break prevents a device to mock jump and marks mixed provenance`() {
        val recorder = WalkFactsRecorder()
        recorder.start()
        recorder.add(sample(37.0, 0))
        recorder.add(sample(37.000117, 10_000))
        recorder.breakSegment()
        recorder.add(sample(35.0, 20_000, isMock = true))
        recorder.add(sample(35.000117, 30_000, isMock = true))

        val facts = requireNotNull(recorder.stop())

        assertEquals(20, facts.durationSeconds)
        assertEquals(26, facts.distanceMeters)
        assertEquals(2, facts.segmentCount)
        assertEquals(WalkFactSource.MIXED, facts.source)
    }

    @Test
    fun `dropped low accuracy fixes make quality limited`() {
        val recorder = WalkFactsRecorder()
        recorder.start()
        recorder.add(sample(37.0, 0))
        recorder.add(sample(37.00005, 5_000, accuracy = 100f))
        recorder.add(sample(37.000117, 10_000))

        val facts = requireNotNull(recorder.stop())

        assertEquals(1, facts.droppedLowAccuracy)
        assertEquals(WalkFactQuality.LIMITED, facts.quality)
    }

    @Test
    fun `stopping without observations produces no invented facts`() {
        val recorder = WalkFactsRecorder()
        recorder.start()

        assertNull(recorder.stop())
    }

    private fun sample(
        latitude: Double,
        elapsedMillis: Long,
        accuracy: Float = 5f,
        isMock: Boolean = false,
    ) = LocationSample(
        point = GeoPoint(latitude, 127.0),
        capturedAtMillis = BASE_WALL_TIME + elapsedMillis,
        elapsedRealtimeNanos = elapsedMillis * 1_000_000,
        accuracyMeters = accuracy,
        speedMetersPerSecond = 1.3f,
        isMock = isMock,
    )

    private companion object {
        const val BASE_WALL_TIME = 1_700_000_000_000L
    }
}
