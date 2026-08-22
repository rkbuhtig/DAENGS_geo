package com.daengs.geo.territory

import com.daengs.geo.location.GeoPoint

data class TerritoryCell(
    val id: String,
    val center: GeoPoint,
    val boundary: List<GeoPoint>,
)

enum class ClaimRejectReason { LOCATION_UNAVAILABLE }

sealed interface ClaimResult {
    data class Claimed(val cell: TerritoryCell) : ClaimResult
    data class AlreadyClaimed(val cell: TerritoryCell) : ClaimResult
    data class Rejected(val reason: ClaimRejectReason) : ClaimResult
}

fun interface CellIndexer {
    fun cellAt(point: GeoPoint): TerritoryCell
}
