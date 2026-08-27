package com.daengs.geo.place

import com.daengs.geo.map.layers.places.FacilityIconGroup
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class PlaceModelsTest {
    private fun fixture(): String = javaClass.getResource("/place_search_response.json")!!.readText()

    private fun response(): PlaceSearchResponse = parse(fixture())

    private fun parse(text: String): PlaceSearchResponse =
        Json.parseToJsonElement(text).jsonObject.toPlaceSearchResponse()

    @Test
    fun `preserves requested group order and server result order`() {
        val response = response()

        assertEquals(listOf(PlaceKind.CAFE, PlaceKind.HOSPITAL), response.groups.map { it.kind })
        assertEquals(
            listOf("먼 주차 카페", "가까운 정보 미상 카페"),
            response.groups.first().results.map { it.place.name },
        )
    }

    @Test
    fun `keeps source ref identity and nullable facts`() {
        val unknown = response().groups.first().results[1].place

        assertEquals(PlaceKey(source = "kto", ref = "cafe-unknown"), unknown.key)
        assertNull(unknown.facts.parking)
        assertEquals(FacilityIconGroup.ETC, unknown.iconGroup)
    }

    @Test
    fun `keeps dog access unknown separate from incompatible`() {
        val results = response().groups.first().results

        assertEquals(DogAccessState.INCOMPATIBLE, results[0].evaluations.dogAccess?.state)
        assertEquals(DogAccessState.UNKNOWN, results[1].evaluations.dogAccess?.state)
        assertEquals("missing_restriction", results[1].evaluations.dogAccess?.reason)
        assertNull(response().groups[1].results.single().evaluations.dogAccess)
    }

    @Test
    fun `parses sorting metadata coverage provenance and medical facts`() {
        val response = response()
        val cafe = response.groups.first()
        val hospital = response.groups[1].results.single().place

        assertEquals(PlaceSortType.DISTANCE_PREFERRED, cafe.sort.type)
        assertEquals(500, cafe.sort.bandMeters)
        assertEquals(1, cafe.sort.coverage.getValue("parking").knownTrue)
        assertEquals("kcisa", cafe.results.first().place.fieldSources
            .getValue("facts.parking").source.source)
        assertEquals(TimeRange("09:00", "18:00"), hospital.facts.medical?.hoursToday?.single())
        assertNull(hospital.facts.medical?.openNow)
    }

    @Test
    fun `unknown canonical kind fails instead of becoming the real etc kind`() {
        val future = fixture().replaceFirst("\"kind\": \"cafe\"", "\"kind\": \"future_kind\"")

        assertThrows(IllegalArgumentException::class.java) { parse(future) }
    }

    @Test
    fun `unknown server discriminants fail instead of borrowing an existing meaning`() {
        val futureSort = fixture().replaceFirst(
            "\"type\": \"distance_preferred\"",
            "\"type\": \"future_sort\"",
        )
        val futureDogState = fixture().replaceFirst(
            "\"state\": \"incompatible\"",
            "\"state\": \"conditional\"",
        )

        assertThrows(IllegalArgumentException::class.java) { parse(futureSort) }
        assertThrows(IllegalArgumentException::class.java) { parse(futureDogState) }
    }
}
