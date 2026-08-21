package com.daengs.geo.hospital

import com.daengs.geo.location.GeoPoint
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

data class RoutePreview(
    val status: String,
    val minutes: Int?,
    val meters: Int?,
    val reason: String?,
)

data class HospitalResult(
    val id: Long,
    val name: String,
    val point: GeoPoint,
    val distanceMeters: Int,
    val address: String?,
    val phone: String?,
    val openNow: Boolean?,
    val preferHits: List<String>,
    val walk: RoutePreview?,
)

data class SuggestedAction(
    val id: String,
    val label: String,
    val source: String,
    val edits: JsonArray,
)

data class ResolutionNotice(
    val what: String,
    val because: String,
    val overrode: String,
)

data class HospitalSearchResponse(
    /** Server-owned state. Keep opaque and send it back without reconstructing it. */
    val state: JsonObject,
    val results: List<HospitalResult>,
    val actions: List<SuggestedAction>,
    val reply: String,
    val showCallCta: Boolean,
    val callReasons: List<String>,
    val resolution: List<ResolutionNotice>,
) {
    val origin: GeoPoint
        get() = GeoPoint(
            latitude = state.requiredDouble("lat"),
            longitude = state.requiredDouble("lng"),
        )
}

fun JsonObject.toHospitalSearchResponse(): HospitalSearchResponse = HospitalSearchResponse(
    state = getValue("state").jsonObject,
    results = getValue("results").jsonArray.map { it.jsonObject.toHospitalResult() },
    actions = arrayOrEmpty("actions").map { it.jsonObject.toSuggestedAction() },
    reply = stringOrNull("reply").orEmpty(),
    showCallCta = booleanOrNull("show_call_cta") ?: false,
    callReasons = arrayOrEmpty("call_reasons").mapNotNull { it.jsonPrimitive.contentOrNull },
    resolution = arrayOrEmpty("resolution").map { element ->
        val value = element.jsonObject
        ResolutionNotice(
            what = value.stringOrNull("what").orEmpty(),
            because = value.stringOrNull("because").orEmpty(),
            overrode = value.stringOrNull("overrode").orEmpty(),
        )
    },
)

private fun JsonObject.toHospitalResult(): HospitalResult {
    val walk = this["transport"]
        ?.takeUnless { it is JsonNull }
        ?.jsonObject
        ?.get("walk")
        ?.takeUnless { it is JsonNull }
        ?.jsonObject
        ?.let { leg ->
            RoutePreview(
                status = leg.stringOrNull("status") ?: "unavailable",
                minutes = leg.intOrNull("min"),
                meters = leg.intOrNull("m"),
                reason = leg.stringOrNull("status_reason"),
            )
        }

    return HospitalResult(
        id = getValue("id").jsonPrimitive.content.toLong(),
        name = getValue("name").jsonPrimitive.content,
        point = GeoPoint(requiredDouble("lat"), requiredDouble("lng")),
        distanceMeters = getValue("distance_m").jsonPrimitive.int,
        address = stringOrNull("address"),
        phone = stringOrNull("phone"),
        openNow = booleanOrNull("open_now"),
        preferHits = arrayOrEmpty("prefer_hit").mapNotNull { it.jsonPrimitive.contentOrNull },
        walk = walk,
    )
}

private fun JsonObject.toSuggestedAction(): SuggestedAction = SuggestedAction(
    id = getValue("id").jsonPrimitive.content,
    label = getValue("label").jsonPrimitive.content,
    source = getValue("source").jsonPrimitive.content,
    edits = getValue("edits").jsonArray,
)

private fun JsonObject.arrayOrEmpty(name: String): JsonArray =
    get(name)?.takeUnless { it is JsonNull }?.jsonArray ?: JsonArray(emptyList())

private fun JsonObject.stringOrNull(name: String): String? =
    get(name)?.takeUnless { it is JsonNull }?.jsonPrimitive?.contentOrNull

private fun JsonObject.booleanOrNull(name: String): Boolean? =
    get(name)?.takeUnless { it is JsonNull }?.jsonPrimitive?.booleanOrNull

private fun JsonObject.intOrNull(name: String): Int? =
    get(name)?.takeUnless { it is JsonNull }?.jsonPrimitive?.intOrNull

private fun JsonObject.requiredDouble(name: String): Double = getValue(name).jsonPrimitive.double
