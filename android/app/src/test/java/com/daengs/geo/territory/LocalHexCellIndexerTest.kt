package com.daengs.geo.territory

import com.daengs.geo.location.GeoPoint
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalHexCellIndexerTest {
    private val indexer = LocalHexCellIndexer(radiusMeters = 28.0)

    @Test
    fun `the same coordinate produces a stable six point cell`() {
        val point = GeoPoint(37.5665, 126.9780)

        val first = indexer.cellAt(point)
        val second = indexer.cellAt(point)

        assertEquals(first, second)
        assertEquals(6, first.boundary.size)
        assertTrue(first.id.startsWith("local-hex:28:"))
    }

    @Test
    fun `distant coordinates produce different cells`() {
        val first = indexer.cellAt(GeoPoint(37.5665, 126.9780))
        val second = indexer.cellAt(GeoPoint(37.5685, 126.9780))

        assertNotEquals(first.id, second.id)
    }
}
