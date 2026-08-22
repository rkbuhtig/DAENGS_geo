package com.daengs.geo.territory

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.location.LocationSample
import kotlinx.coroutines.flow.StateFlow

interface TerritoryRepository {
    val claimedCells: StateFlow<List<TerritoryCell>>

    fun cellAt(point: GeoPoint): TerritoryCell

    /** Callers hold a fix before claiming; "no location yet" is a UI state, not a claim outcome. */
    suspend fun claim(sample: LocationSample): ClaimResult
}
