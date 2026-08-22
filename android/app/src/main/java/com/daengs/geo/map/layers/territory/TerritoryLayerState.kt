package com.daengs.geo.map.layers.territory

import com.daengs.geo.territory.TerritoryCell

/** Hiding the layer means handing over no cells, not setting a flag the renderer must honor. */
data class TerritoryLayerState(
    val claimedCells: List<TerritoryCell> = emptyList(),
    val previewCell: TerritoryCell? = null,
)
