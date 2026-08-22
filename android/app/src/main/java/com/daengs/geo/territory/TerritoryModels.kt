package com.daengs.geo.territory

import com.daengs.geo.location.GeoPoint

data class TerritoryCell(
    val id: String,
    val center: GeoPoint,
    val boundary: List<GeoPoint>,
)

/**
 * Why a claim was refused. The evidence policy lives with the repository so a remote
 * implementation can reuse the vocabulary instead of collapsing everything into one reason.
 */
enum class ClaimRejectReason { MOCK_LOCATION, LOW_ACCURACY }

sealed interface ClaimResult {
    data class Claimed(val cell: TerritoryCell) : ClaimResult

    data class AlreadyClaimed(val cell: TerritoryCell) : ClaimResult

    data class Rejected(val reason: ClaimRejectReason) : ClaimResult
}

fun interface CellIndexer {
    fun cellAt(point: GeoPoint): TerritoryCell
}
