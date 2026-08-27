package com.daengs.geo.map.features.places

import com.daengs.geo.place.DogAccessState
import com.daengs.geo.place.PlaceKey
import com.daengs.geo.place.PlaceKind
import com.daengs.geo.place.PlaceSearchResponse
import com.daengs.geo.place.toPlaceSearchResponse
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PlaceDiscoveryPanelTest {
    @Test
    fun `category chips expose every canonical fact kind exactly once`() {
        assertEquals(PlaceKind.entries.toSet(), PLACE_CATEGORIES.map { it.kind }.toSet())
        assertEquals(PlaceKind.entries.size, PLACE_CATEGORIES.size)
        assertEquals(PlaceKind.CAFE, DEFAULT_PLACE_KIND)
        assertFalse(DEFAULT_PLACE_KIND == PlaceKind.SHOPPING)
    }

    @Test
    fun `marker projection preserves server order and stable source ref selection`() {
        val response = response()
        val selected = PlaceKey("kto", "cafe-unknown")
        val state = PlaceDiscoveryState(response = response, selectedPlaceKey = selected)

        val markers = canonicalPlaceMarkers(state)
        val keys = canonicalPlaceKeysByMarker(state)

        assertEquals(
            listOf("먼 주차 카페", "가까운 정보 미상 카페", "댕스동물병원"),
            markers.map { it.label },
        )
        assertFalse(markers[0].selected)
        assertTrue(markers[1].selected)
        assertEquals(selected, keys.getValue(markers[1].id))
    }

    @Test
    fun `marker identity cannot collide when source and ref boundaries differ`() {
        assertNotEquals(
            placeMarkerId(PlaceKey(source = "ab", ref = "c")),
            placeMarkerId(PlaceKey(source = "a", ref = "bc")),
        )
    }

    @Test
    fun `labels keep unknown facts separate from negative facts`() {
        assertEquals("주차 가능", parkingLabel(true))
        assertEquals("주차 불가", parkingLabel(false))
        assertEquals("주차 정보 없음", parkingLabel(null))
        assertEquals("조건 불일치", dogAccessLabel(DogAccessState.INCOMPATIBLE))
        assertEquals("정보 부족 · 확인 필요", dogAccessLabel(DogAccessState.UNKNOWN))
        assertEquals("시설 제한 정보 없음", dogAccessReasonLabel("missing_restriction"))
    }

    @Test
    fun `sorting explanation comes from server metadata`() {
        val groups = response().groups

        assertEquals("500m 구간 안에서 주차 가능 우선", sortLabel(groups[0]))
        assertEquals("가까운 순", sortLabel(groups[1]))
        assertEquals(
            DogAccessCoverage(compatible = 0, incompatible = 1, unknown = 1),
            dogAccessCoverage(groups[0]),
        )
        assertEquals(null, dogAccessCoverage(groups[1]))
    }

    private fun response(): PlaceSearchResponse {
        val text = javaClass.getResource("/place_search_response.json")!!.readText()
        return Json.parseToJsonElement(text).jsonObject.toPlaceSearchResponse()
    }
}
