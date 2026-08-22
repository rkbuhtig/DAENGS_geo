package com.daengs.geo.location

import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ReplayLocationSourceTest {
    @Test
    fun `replay emits every point in order and scales its delay`() = runBlocking {
        val points = listOf(
            GeoPoint(37.0, 127.0),
            GeoPoint(37.0001, 127.0001),
            GeoPoint(37.0002, 127.0002),
        )
        val delays = mutableListOf<Long>()
        val source = ReplayLocationSource(
            points = points,
            speedMultiplier = 5.0,
            sleeper = { delays += it },
            nowMillis = { 123L },
            elapsedRealtimeNanos = { 456L },
            segmentDurationMillis = { _, _ -> 1_000L },
        )

        val samples = source.locationUpdates().toList()

        assertEquals(points, samples.map { it.point })
        assertEquals(listOf(200L, 200L), delays)
        assertTrue(samples.all { it.isMock })
        assertEquals(listOf(123L, 1_123L, 2_123L), samples.map { it.capturedAtMillis })
        assertEquals(
            listOf(456L, 1_000_000_456L, 2_000_000_456L),
            samples.map { it.elapsedRealtimeNanos },
        )
        assertTrue(samples.all { it.speedMetersPerSecond == 1.3f })
    }

    @Test
    fun `loop is anchored at the supplied point`() {
        val origin = GeoPoint(37.5665, 126.9780)

        val route = ReplayLocationSource.loopAround(origin)

        assertEquals(origin, route.first())
        assertEquals(origin, route.last())
        assertTrue(route.distinct().size > 8)
    }
}
