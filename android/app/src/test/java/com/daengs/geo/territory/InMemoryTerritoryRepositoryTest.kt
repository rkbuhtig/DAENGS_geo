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
        val sample = sample()

        val first = repository.claim(sample)
        val second = repository.claim(sample)

        assertTrue(first is ClaimResult.Claimed)
        assertTrue(second is ClaimResult.AlreadyClaimed)
        assertEquals(1, repository.claimedCells.value.size)
    }

    @Test
    fun `a replayed fix cannot claim a cell`() = runBlocking {
        val repository = InMemoryTerritoryRepository(LocalHexCellIndexer())

        val result = repository.claim(sample(isMock = true))

        assertEquals(ClaimResult.Rejected(ClaimRejectReason.MOCK_LOCATION), result)
        assertTrue(repository.claimedCells.value.isEmpty())
    }

    @Test
    fun `a coarse fix cannot claim a cell`() = runBlocking {
        val repository = InMemoryTerritoryRepository(LocalHexCellIndexer(), maxAccuracyMeters = 50f)

        val result = repository.claim(sample(accuracy = 2_000f))

        assertEquals(ClaimResult.Rejected(ClaimRejectReason.LOW_ACCURACY), result)
        assertTrue(repository.claimedCells.value.isEmpty())
    }

    private fun sample(
        isMock: Boolean = false,
        accuracy: Float? = 8f,
    ) = LocationSample(
        point = GeoPoint(37.5665, 126.9780),
        capturedAtMillis = 1L,
        accuracyMeters = accuracy,
        isMock = isMock,
    )
}
