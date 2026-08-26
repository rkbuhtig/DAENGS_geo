package com.daengs.geo.place

import com.daengs.geo.location.GeoPoint
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class PlaceSearchRequestTest {
    @Test
    fun `emits canonical kinds conditions and explicit preference`() {
        val json = PlaceSearchRequest(
            origin = GeoPoint(37.556, 126.923),
            kinds = listOf(PlaceKind.PET_SHOP, PlaceKind.SHOPPING),
            limitPerKind = 2_500,
            dogId = " janggun ",
            preferParking = true,
        ).toJson()

        assertEquals(
            listOf("pet_shop", "shopping"),
            json.getValue("kinds").jsonArray.map { it.jsonPrimitive.content },
        )
        assertEquals("janggun", json.getValue("conditions").jsonObject
            .getValue("dog_id").jsonPrimitive.content)
        assertTrue(json.getValue("preferences").jsonObject
            .getValue("parking").jsonPrimitive.content.toBoolean())
    }

    @Test
    fun `omits preferences and empty conditions rather than sending false claims`() {
        val json = PlaceSearchRequest(
            origin = GeoPoint(37.556, 126.923),
            kinds = listOf(PlaceKind.CAFE),
            dogId = "   ",
            preferParking = false,
        ).toJson()

        assertFalse(json.containsKey("preferences"))
        assertFalse(json.containsKey("conditions"))
    }

    @Test
    fun `request vocabulary cannot express retired goods kind`() {
        assertFalse(PlaceKind.entries.any { it.wire == "goods" })
    }

    @Test
    fun `rejects duplicate kinds and requests beyond the shared result budget`() {
        assertThrows(IllegalArgumentException::class.java) {
            PlaceSearchRequest(
                origin = GeoPoint(37.556, 126.923),
                kinds = listOf(PlaceKind.CAFE, PlaceKind.CAFE),
            )
        }
        assertThrows(IllegalArgumentException::class.java) {
            PlaceSearchRequest(
                origin = GeoPoint(37.556, 126.923),
                kinds = listOf(PlaceKind.CAFE, PlaceKind.TRAVEL),
                limitPerKind = 3_000,
            )
        }
    }
}
