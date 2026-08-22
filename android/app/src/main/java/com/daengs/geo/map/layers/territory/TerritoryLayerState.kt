package com.daengs.geo.map.layers.territory

import com.daengs.geo.territory.TerritoryCell

data class TerritoryLayerState(
    val claimedCells: List<TerritoryCell> = emptyList(),
    val previewCell: TerritoryCell? = null,
    val visible: Boolean = false,
)
