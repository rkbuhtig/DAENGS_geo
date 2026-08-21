package com.daengs.geo.hospital

import com.daengs.geo.location.GeoPoint
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class SearchRequestBuilderTest {
    private val state = Json.parseToJsonElement(
        javaClass.getResource("/hospital_search_response.json")!!.readText(),
    ).jsonObject.getValue("state").jsonObject

    @Test
    fun `follow device includes the latest origin when a search is requested`() {
        val request = SearchRequestBuilder.build(
            SearchSession(
                state = state,
                deviceLocation = GeoPoint(37.1, 127.2),
                mode = LocationMode.FOLLOW_DEVICE,
            ),
        )

        assertEquals(37.1, request.getValue("origin").jsonArray[0].jsonPrimitive.content.toDouble(), 0.0)
        assertEquals(127.2, request.getValue("origin").jsonArray[1].jsonPrimitive.content.toDouble(), 0.0)
        assertSame(state, request.getValue("state"))
    }

    @Test
    fun `pinned mode omits origin and keeps server state and action edits opaque`() {
        val edits = Json.parseToJsonElement(
            """[{"tool":"future_tool","args":{"nested":{"value":1}}}]""",
        ).jsonArray

        val request = SearchRequestBuilder.build(
            SearchSession(
                state = state,
                deviceLocation = GeoPoint(35.0, 129.0),
                mode = LocationMode.PINNED,
            ),
            edits = edits,
        )

        assertFalse(request.containsKey("origin"))
        assertSame(state, request.getValue("state"))
        assertSame(edits, request.getValue("edits"))
        assertTrue(request.getValue("state").jsonObject.containsKey("future_server_field"))
    }

    @Test
    fun `first pinned request is rejected before reaching the network`() {
        assertThrows(IllegalArgumentException::class.java) {
            SearchRequestBuilder.build(
                SearchSession(
                    state = null,
                    deviceLocation = GeoPoint(37.1, 127.2),
                    mode = LocationMode.PINNED,
                ),
            )
        }
    }

    @Test
    fun `set origin edit does not smuggle a top level origin`() {
        val edit = SearchRequestBuilder.setOriginEdit(GeoPoint(37.4, 126.8))
        val request = SearchRequestBuilder.build(
            SearchSession(state, GeoPoint(37.1, 127.2), LocationMode.PINNED),
            edits = edit,
        )

        assertFalse(request.containsKey("origin"))
        assertEquals("set_origin", request.getValue("edits").jsonArray[0].jsonObject["tool"]!!.jsonPrimitive.content)
    }
}
