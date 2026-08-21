package com.daengs.geo.hospital

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HospitalModelsTest {
    private fun response(): HospitalSearchResponse {
        val text = javaClass.getResource("/hospital_search_response.json")!!.readText()
        return Json.parseToJsonElement(text).jsonObject.toHospitalSearchResponse()
    }

    @Test
    fun `parses rendering fields while retaining opaque state`() {
        val response = response()

        assertEquals(37.5665, response.origin.latitude, 0.0)
        assertTrue(response.state.containsKey("future_server_field"))
        assertEquals("댕스동물병원", response.results.single().name)
        assertNull(response.results.single().openNow)
        assertEquals("estimate", response.results.single().walk?.status)
        assertEquals(3, response.results.single().walk?.minutes)
    }

    @Test
    fun `keeps multi edit action payload unchanged`() {
        val response = response()
        val action = response.actions.single()

        assertEquals("walk_without_stairs", action.id)
        assertEquals(2, action.edits.size)
        assertEquals("policy", action.source)
    }

    @Test
    fun `parses mandatory safety surface`() {
        val response = response()

        assertTrue(response.showCallCta)
        assertEquals(listOf("방문 전 전화 확인"), response.callReasons)
        assertEquals("거리 설정", response.resolution.single().overrode)
    }
}
