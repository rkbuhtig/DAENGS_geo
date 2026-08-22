package com.daengs.geo.territory

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.location.LocationSample
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class InMemoryTerritoryRepository(
    private val indexer: CellIndexer,
) : TerritoryRepository {
    private val lock = Any()
    private val _claimedCells = MutableStateFlow<List<TerritoryCell>>(emptyList())
    override val claimedCells: StateFlow<List<TerritoryCell>> = _claimedCells.asStateFlow()

    override fun cellAt(point: GeoPoint): TerritoryCell = indexer.cellAt(point)

    override suspend fun claim(sample: LocationSample?): ClaimResult {
        if (sample == null) return ClaimResult.Rejected(ClaimRejectReason.LOCATION_UNAVAILABLE)
        val cell = indexer.cellAt(sample.point)
        return synchronized(lock) {
            val existing = _claimedCells.value.firstOrNull { it.id == cell.id }
            if (existing != null) {
                ClaimResult.AlreadyClaimed(existing)
            } else {
                _claimedCells.value = _claimedCells.value + cell
                ClaimResult.Claimed(cell)
            }
        }
    }
}
