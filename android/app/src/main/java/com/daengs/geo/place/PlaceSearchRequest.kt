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

/**
 * 검색에 싣는 개의 **값**. identity(dog_id)가 아니다 — 서버는 프로필을 조회하지 않고
 * 받은 값을 그대로 평가한다 (결정 #73). dog_id → 값 projection 은 프로필 소유자의 일이다.
 */
data class DogSearchContext(
    val size: DogSize? = null,
    val weightKg: Double? = null,
    val ageYears: Double? = null,
) {
    init {
        require(size != null || weightKg != null || ageYears != null) {
            "DogSearchContext requires at least one of size, weightKg, ageYears"
        }
    }
}

/** Typed request for the canonical place endpoint. `goods` cannot be represented here. */
data class PlaceSearchRequest(
    val origin: GeoPoint,
    val radiusMeters: Int = 3_000,
    val kinds: List<PlaceKind>,
    val limitPerKind: Int? = null,
    val dogSize: DogSize? = null,
    val dogWeightKg: Double? = null,
    val dogAgeYears: Double? = null,
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
        require(dogAgeYears == null || dogAgeYears in 0.0..40.0) {
            "dogAgeYears must be between 0 and 40"
        }
    }

    private val hasDogConditions: Boolean
        get() = dogSize != null || dogWeightKg != null || dogAgeYears != null

    fun toJson(): JsonObject = buildJsonObject {
        put("lat", origin.latitude)
        put("lng", origin.longitude)
        put("radius_m", radiusMeters)
        put("kinds", buildJsonArray { kinds.forEach { add(JsonPrimitive(it.wire)) } })
        limitPerKind?.let { put("limit_per_kind", it) }

        // 서버 계약(결정 #73)은 값만 받고 `extra="forbid"` 다 — dog_id 를 보내면 422.
        if (hasDogConditions) {
            put("conditions", buildJsonObject {
                dogSize?.let { put("dog_size", it.wire) }
                dogWeightKg?.let { put("dog_weight_kg", it) }
                dogAgeYears?.let { put("dog_age_years", it) }
            })
        }
        if (preferParking) {
            put("preferences", buildJsonObject { put("parking", true) })
        }
    }
}
