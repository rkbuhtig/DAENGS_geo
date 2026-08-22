package com.daengs.geo.location

import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Test

class LocationTrackerTest {
    @Test
    fun `starting a new feed cancels the previous subscription`() = runBlocking {
        val active = AtomicInteger(0)
        val starts = AtomicInteger(0)
        val source = object : LocationSource {
            override suspend fun currentLocation() = sample()

            override fun locationUpdates(config: LocationUpdateConfig): Flow<LocationSample> = flow {
                starts.incrementAndGet()
                active.incrementAndGet()
                try {
                    awaitCancellation()
                } finally {
                    active.decrementAndGet()
                }
            }
        }
        val tracker = LocationTracker(this)

        tracker.start(source)
        yield()
        assertEquals(1, active.get())

        tracker.start(source)
        yield()
        assertEquals(2, starts.get())
        assertEquals(1, active.get())

        tracker.stop()
        yield()
        assertEquals(0, active.get())
    }

    private fun sample() = LocationSample(
        point = GeoPoint(37.0, 127.0),
        capturedAtMillis = 1L,
    )
}
