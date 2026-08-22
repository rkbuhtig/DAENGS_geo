package com.daengs.geo.territory

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.location.LocationSample
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class InMemoryTerritoryRepositoryTest {
    @Test
    fun `claiming a cell twice reports the no-op without duplicating it`() = runBlocking {
        val repository = InMemoryTerritoryRepository(LocalHexCellIndexer())
        val sample = LocationSample(GeoPoint(37.5665, 126.9780), capturedAtMillis = 1L)

        val first = repository.claim(sample)
        val second = repository.claim(sample)

        assertTrue(first is ClaimResult.Claimed)
        assertTrue(second is ClaimResult.AlreadyClaimed)
        assertEquals(1, repository.claimedCells.value.size)
    }

    @Test
    fun `claim without a current sample is an explicit rejection`() = runBlocking {
        val repository = InMemoryTerritoryRepository(LocalHexCellIndexer())

        val result = repository.claim(null)

        assertEquals(
            ClaimResult.Rejected(ClaimRejectReason.LOCATION_UNAVAILABLE),
            result,
        )
    }
}
