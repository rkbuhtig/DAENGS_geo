package com.daengs.geo.place

import com.daengs.geo.location.GeoPoint
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

private const val MAX_KINDS_PER_REQUEST = 6
private const val MAX_RESULTS_PER_KIND = 3_000
private const val MAX_TOTAL_RESULTS = 5_000

/** Typed request for the canonical place endpoint. `goods` cannot be represented here. */
data class PlaceSearchRequest(
    val origin: GeoPoint,
    val radiusMeters: Int = 3_000,
    val kinds: List<PlaceKind>,
    val limitPerKind: Int? = null,
    val dogId: String? = null,
    val dogSize: DogSize? = null,
    val dogWeightKg: Double? = null,
    val preferParking: Boolean = false,
) {
    init {
        require(origin.latitude in 32.0..40.0) { "latitude must be inside the server contract" }
        require(origin.longitude in 123.0..133.0) { "longitude must be inside the server contract" }
        require(radiusMeters in 100..20_000) { "radiusMeters must be between 100 and 20000" }
        require(kinds.isNotEmpty()) { "kinds must not be empty" }
        require(kinds.size <= MAX_KINDS_PER_REQUEST) { "at most 6 kinds are allowed" }
        require(kinds.distinct().size == kinds.size) { "kinds must be unique" }
        require(limitPerKind == null || limitPerKind in 1..MAX_RESULTS_PER_KIND) {
            "limitPerKind must be between 1 and 3000"
        }
        require(limitPerKind == null || limitPerKind * kinds.size <= MAX_TOTAL_RESULTS) {
            "limitPerKind across all kinds must not exceed 5000 results"
        }
        require(dogWeightKg == null || dogWeightKg > 0.0 && dogWeightKg <= 200.0) {
            "dogWeightKg must be greater than 0 and at most 200"
        }
        require(dogWeightKg == null || normalizedDogId != null || dogSize != null) {
            "dogWeightKg requires dogId or dogSize"
        }
    }

    private val normalizedDogId: String? get() = dogId?.trim()?.takeIf(String::isNotEmpty)

    fun toJson(): JsonObject = buildJsonObject {
        put("lat", origin.latitude)
        put("lng", origin.longitude)
        put("radius_m", radiusMeters)
        put("kinds", buildJsonArray { kinds.forEach { add(JsonPrimitive(it.wire)) } })
        limitPerKind?.let { put("limit_per_kind", it) }

        if (normalizedDogId != null || dogSize != null) {
            put("conditions", buildJsonObject {
                normalizedDogId?.let { put("dog_id", it) }
                dogSize?.let { put("dog_size", it.wire) }
                dogWeightKg?.let { put("dog_weight_kg", it) }
            })
        }
        if (preferParking) {
            put("preferences", buildJsonObject { put("parking", true) })
        }
    }
}
