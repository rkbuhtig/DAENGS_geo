package com.daengs.geo.journey

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.place.PlaceKey
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class JourneyModelsTest {
    @Test
    fun `request uses real origin and canonical Place coordinates without an internal id`() {
        val request = PlaceJourneyRequest(
            origin = GeoPoint(37.4979, 127.0276),
            destinationKey = PlaceKey("medical", "hospital-7"),
            destinationName = "댕스동물병원",
            destination = GeoPoint(37.5145, 127.0316),
            dogId = " janggun ",
        ).toJson()

        assertEquals(
            listOf("37.4979", "127.0276"),
            request.getValue("origin").jsonArray.map { it.jsonPrimitive.content },
        )
        val destination = request.getValue("dests").jsonArray.single().jsonObject
        assertFalse(destination.containsKey("id"))
        assertEquals("37.5145", destination.getValue("lat").jsonPrimitive.content)
        assertEquals("127.0316", destination.getValue("lng").jsonPrimitive.content)
        assertEquals("janggun", request.getValue("dog_id").jsonPrimitive.content)
        assertTrue(request.getValue("measured").jsonPrimitive.boolean)
        assertFalse(request.getValue("with_polyline").jsonPrimitive.boolean)
    }

    @Test
    fun `response keeps route status priority and provider handoff`() {
        val response = fixture()
        val item = response.items.single()

        assertEquals("dog", response.companion)
        assertEquals(listOf(JourneyMode.WALK, JourneyMode.CAR), item.modePriority)
        assertEquals(JourneyRouteStatus.ESTIMATE, item.legs.getValue(JourneyMode.WALK).status)
        assertEquals(31, item.legs.getValue(JourneyMode.WALK).minutes)
        assertTrue(item.legs.getValue(JourneyMode.WALK).handoff!!.naver.startsWith("nmap://route/walk"))
        assertEquals(JourneyRouteStatus.UNAVAILABLE, item.legs.getValue(JourneyMode.CAR).status)
        assertNull(item.legs[JourneyMode.TRANSIT])
    }

    private fun fixture(): JourneyResponse {
        val text = javaClass.getResource("/journey_response.json")!!.readText()
        return Json.parseToJsonElement(text).jsonObject.toJourneyResponse()
    }
}
