package com.daengs.app.place

import com.daengs.app.location.GeoPoint
import com.daengs.app.ui.places.dogEvaluationLabel
import java.io.File
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

/** Opt-in public read-only probe. Uses synthetic dog values, never account tokens. */
class PlaceProfileLiveProbe {
    @Test fun developmentServerSupportsActualKotlinClientAndBatchContract() = runBlocking {
        val endpoint = "http://daengback.weareithero.cloud"
        val api = PlaceApi(baseUrl = { endpoint })
        val records = mutableListOf<JsonObject>()
        val a = PlaceDogSnapshot("probe-a", "v1", weightKg = 9.0, ageYears = 2.0)
        val b = PlaceDogSnapshot("probe-b", "v1")
        val base = PlaceSearchRequest(GeoPoint(37.5446, 127.0559), kinds = listOf(PlaceKind.CAFE), limitPerKind = 20)
        suspend fun probe(name: String, request: PlaceSearchRequest): PlaceSearchResponse {
            val response = api.search(request)
            response.requireDogEcho(request)
            assertEquals(request.kinds, response.groups.map { it.kind })
            records += buildJsonObject {
                put("case", name)
                put("request", request.toJson())
                put("count", response.groups.sumOf { it.results.size })
                put("truncated", response.groups.any { it.truncated })
                put("labels", buildJsonArray {
                    response.groups.flatMap { it.results }.take(2).forEach { hit ->
                        hit.evaluations.dogs.forEach { add(JsonPrimitive(dogEvaluationLabel(it))) }
                    }
                })
            }
            return response
        }
        val baseline = probe("no_selection", base)
        assertTrue(baseline.groups.single().results.isNotEmpty())
        probe("one_dog", base.copy(dogs = listOf(a)))
        val two = probe("two_dogs", base.copy(dogs = listOf(a, b)))
        assertEquals(baseline.groups.single().results.map { it.place.key }, two.groups.single().results.map { it.place.key })
        val updated = base.copy(dogs = listOf(a.copy(revision = "v2", weightKg = 11.0), b))
        probe("updated_snapshot", updated)
        probe("moved_and_radius", updated.copy(origin = GeoPoint(37.5456, 127.0569), radiusMeters = 5000))
        val named = probe("name_filter", updated.copy(nameQuery = "구욱희씨"))
        assertTrue(named.groups.single().results.isNotEmpty())
        assertTrue(named.groups.single().results.all { it.place.name.contains("구욱희씨") })
        probe("selection_cleared", base)
        val requests = PlaceKind.entries.chunked(6).map { updated.copy(kinds = it, radiusMeters = 5000, preferParking = true) }
        val all = searchPlaceBatches(PlaceSearchRepository { request ->
            probe("all_${request.kinds.first().wire}", request)
        }, requests)
        assertEquals(PlaceKind.entries, all.groups.map { it.kind })
        assertEquals(updated.dogs, all.dogs)
        val hits = all.overviewHits(true)
        assertEquals(hits.size, hits.map { it.place.key }.distinct().size)
        val output = requireNotNull(System.getenv("DAENGS_PROFILE_PROBE_OUTPUT"))
        File(output).writeText(buildJsonObject {
            put("endpoint", endpoint)
            put("captured_at", java.time.Instant.now().toString())
            put("synthetic_profiles", true)
            put("all_unique_count", hits.size)
            put("cases", JsonArray(records))
        }.toString())
    }
}
