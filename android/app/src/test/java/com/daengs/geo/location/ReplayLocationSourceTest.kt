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
            tickMillis = 1_000,
            sleeper = { delays += it },
            nowMillis = { 123L },
        )

        val samples = source.locationUpdates().toList()

        assertEquals(points, samples.map { it.point })
        assertEquals(listOf(200L, 200L), delays)
        assertTrue(samples.all { it.isMock })
        assertTrue(samples.all { it.capturedAtMillis == 123L })
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
