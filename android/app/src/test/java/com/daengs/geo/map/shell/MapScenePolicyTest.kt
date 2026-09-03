package com.daengs.geo.map.shell

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.map.layers.places.PlaceMarkerState
import com.daengs.geo.map.layers.territory.TerritoryLayerState
import com.daengs.geo.map.layers.trail.TrailLayerState
import com.daengs.geo.territory.TerritoryCell
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MapScenePolicyTest {
    private val point = GeoPoint(37.5665, 126.9780)
    private val place = PlaceMarkerState(id = "place", point = point, label = "시설")
    private val territory = TerritoryCell(id = "territory", center = point, boundary = listOf(point))
    private val sources = MapSceneSources(
        currentPosition = point,
        places = listOf(place),
        trail = TrailLayerState(paths = listOf(listOf(point, point))),
        territory = TerritoryLayerState(claimedCells = listOf(territory), previewCell = territory),
    )

    @Test
    fun `place search receives only place overlays`() {
        val policy = mapDisplayPolicy(
            purpose = MapPurpose.PLACE_SEARCH,
            trailPreferred = true,
            walkActive = true,
        )

        val scene = composeMapScene(policy, sources)

        assertEquals(listOf(place), scene.places)
        assertTrue(scene.trail.paths.isEmpty())
        assertTrue(scene.territory.claimedCells.isEmpty())
        assertEquals(BaseMapStyle.SEARCH_DETAIL, scene.baseMapStyle)
    }

    @Test
    fun `walk receives its trail without place or territory overlays`() {
        val policy = mapDisplayPolicy(
            purpose = MapPurpose.WALK,
            trailPreferred = true,
            walkActive = true,
        )

        val scene = composeMapScene(policy, sources)

        assertTrue(scene.places.isEmpty())
        assertEquals(sources.trail, scene.trail)
        assertTrue(scene.territory.claimedCells.isEmpty())
        assertEquals(BaseMapStyle.WALK_CONTEXT, scene.baseMapStyle)
    }

    @Test
    fun `territory receives territory and only a currently active walk trail`() {
        val active = composeMapScene(
            mapDisplayPolicy(MapPurpose.TERRITORY, trailPreferred = true, walkActive = true),
            sources,
        )
        val inactive = composeMapScene(
            mapDisplayPolicy(MapPurpose.TERRITORY, trailPreferred = true, walkActive = false),
            sources,
        )

        assertTrue(active.places.isEmpty())
        assertEquals(sources.territory, active.territory)
        assertEquals(sources.trail, active.trail)
        assertTrue(inactive.trail.paths.isEmpty())
        assertEquals(BaseMapStyle.TERRITORY_FOCUSED, active.baseMapStyle)
    }

    @Test
    fun `current position survives every purpose`() {
        MapPurpose.entries.forEach { purpose ->
            val policy = mapDisplayPolicy(purpose, trailPreferred = false, walkActive = false)
            assertEquals(point, composeMapScene(policy, sources).currentPosition)
        }
    }

    @Test
    fun `trail preference cannot leak a trail into place search`() {
        val visible = mapDisplayPolicy(MapPurpose.WALK, trailPreferred = true, walkActive = true)
        val hiddenByUser = mapDisplayPolicy(MapPurpose.WALK, trailPreferred = false, walkActive = true)
        val hiddenByPurpose = mapDisplayPolicy(
            MapPurpose.PLACE_SEARCH,
            trailPreferred = true,
            walkActive = true,
        )

        assertTrue(visible.showTrail)
        assertEquals(false, hiddenByUser.showTrail)
        assertEquals(false, hiddenByPurpose.showTrail)
    }
}
