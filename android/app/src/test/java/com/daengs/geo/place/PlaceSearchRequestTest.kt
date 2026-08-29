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
        // 장군의 값. 서버는 identity(dog_id)를 받지 않는다 — 결정 #73.
        val json = PlaceSearchRequest(
            origin = GeoPoint(37.556, 126.923),
            kinds = listOf(PlaceKind.PET_SHOP, PlaceKind.SHOPPING),
            limitPerKind = 2_500,
            dogSize = DogSize.LARGE,
            dogWeightKg = 34.0,
            dogAgeYears = 11.5,
            preferParking = true,
        ).toJson()

        assertEquals(
            listOf("pet_shop", "shopping"),
            json.getValue("kinds").jsonArray.map { it.jsonPrimitive.content },
        )
        val conditions = json.getValue("conditions").jsonObject
        assertEquals("large", conditions.getValue("dog_size").jsonPrimitive.content)
        assertEquals(34.0, conditions.getValue("dog_weight_kg").jsonPrimitive.content.toDouble(), 0.0)
        assertEquals(11.5, conditions.getValue("dog_age_years").jsonPrimitive.content.toDouble(), 0.0)
        // 서버 계약이 extra="forbid" 라 dog_id 가 새어 나가면 422 다.
        assertFalse(conditions.containsKey("dog_id"))
        assertTrue(json.getValue("preferences").jsonObject
            .getValue("parking").jsonPrimitive.content.toBoolean())
    }

    @Test
    fun `omits preferences and empty conditions rather than sending false claims`() {
        val json = PlaceSearchRequest(
            origin = GeoPoint(37.556, 126.923),
            kinds = listOf(PlaceKind.CAFE),
            preferParking = false,
        ).toJson()

        assertFalse(json.containsKey("preferences"))
        assertFalse(json.containsKey("conditions"))
    }

    @Test
    fun `dog context requires at least one value like the server contract`() {
        assertThrows(IllegalArgumentException::class.java) { DogSearchContext() }
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
