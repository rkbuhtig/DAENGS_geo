package com.daengs.geo.map.layers.trail

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.location.LocationSample
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TrailRecorderTest {
    @Test
    fun `recording pause and resume control which samples enter the trail`() {
        val recorder = TrailRecorder(minDistanceMeters = 1.0)
        val first = sample(37.0, 127.0, 1L)
        val second = sample(37.0001, 127.0, 2L)
        val third = sample(37.0002, 127.0, 3L)

        recorder.start()
        recorder.add(first)
        recorder.pause()
        recorder.add(second)
        assertEquals(listOf(first), recorder.snapshot().samples)

        recorder.resume()
        val snapshot = recorder.add(third)
        assertEquals(listOf(first, third), snapshot.samples)
        assertTrue(snapshot.distanceMeters > 20.0)
    }

    @Test
    fun `bad accuracy and jitter are ignored`() {
        val recorder = TrailRecorder(minDistanceMeters = 3.0, maxAccuracyMeters = 20f)
        recorder.start()
        recorder.add(sample(37.0, 127.0, 1L, accuracy = 5f))
        recorder.add(sample(37.000001, 127.0, 2L, accuracy = 5f))
        recorder.add(sample(37.001, 127.0, 3L, accuracy = 100f))

        assertEquals(1, recorder.snapshot().samples.size)
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
