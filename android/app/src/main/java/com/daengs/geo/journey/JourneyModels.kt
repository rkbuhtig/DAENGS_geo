package com.daengs.geo.journey

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.place.PlaceKey
import com.daengs.geo.place.PlaceResult
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

enum class JourneyMode(val wire: String) {
    WALK("walk"),
    CAR("car"),
    TRANSIT("transit"),
    ;

    companion object {
        private val byWire = entries.associateBy(JourneyMode::wire)

        fun fromWire(value: String): JourneyMode = requireNotNull(byWire[value]) {
            "Unknown journey mode: $value"
        }
    }
}

enum class JourneyRouteStatus {
    MEASURED,
    ESTIMATE,
    UNAVAILABLE,
    ;

    companion object {
        fun fromWire(value: String): JourneyRouteStatus = when (value) {
            "measured" -> MEASURED
            "estimate" -> ESTIMATE
            "unavailable" -> UNAVAILABLE
            else -> throw IllegalArgumentException("Unknown journey route status: $value")
        }
    }
}

data class JourneyHandoff(
    val naver: String,
    val kakao: String,
    val tmap: String,
)

data class JourneyLeg(
    val status: JourneyRouteStatus,
    val statusReason: String?,
    val minutes: Int?,
    val meters: Int?,
    val source: String,
    val handoff: JourneyHandoff?,
)

data class JourneyItem(
    val destination: GeoPoint,
    val name: String,
    val straightMeters: Int,
    val modePriority: List<JourneyMode>,
    val legs: Map<JourneyMode, JourneyLeg>,
)

data class JourneyResponse(
    val companion: String,
    val items: List<JourneyItem>,
)

/** One canonical Place is one journey destination. Internal DB ids never cross this boundary. */
data class PlaceJourneyRequest(
    val origin: GeoPoint,
    val destinationKey: PlaceKey,
    val destinationName: String,
    val destination: GeoPoint,
    val dogId: String? = null,
) {
    constructor(origin: GeoPoint, place: PlaceResult, dogId: String? = null) : this(
        origin = origin,
        destinationKey = place.key,
        destinationName = place.name,
        destination = place.point,
        dogId = dogId,
    )

    fun toJson(): JsonObject = buildJsonObject {
        put("origin", buildJsonArray {
            add(JsonPrimitive(origin.latitude))
            add(JsonPrimitive(origin.longitude))
        })
        put("dests", buildJsonArray {
            add(buildJsonObject {
                put("lat", destination.latitude)
                put("lng", destination.longitude)
                put("name", destinationName)
            })
        })
        put("companion", "dog")
        dogId?.trim()?.takeIf(String::isNotEmpty)?.let { put("dog_id", it) }
        // The first Android cut hands navigation to a provider app; it does not render a route line.
        put("measured", true)
        put("with_polyline", false)
    }
}

fun JsonObject.toJourneyResponse(): JourneyResponse = JourneyResponse(
    companion = getValue("companion").jsonPrimitive.content,
    items = getValue("items").jsonArray.map { element -> element.jsonObject.toJourneyItem() },
)

private fun JsonObject.toJourneyItem(): JourneyItem {
    val transport = getValue("transport").jsonObject
    return JourneyItem(
        destination = GeoPoint(
            latitude = getValue("lat").jsonPrimitive.content.toDouble(),
            longitude = getValue("lng").jsonPrimitive.content.toDouble(),
        ),
        name = getValue("name").jsonPrimitive.content,
        straightMeters = transport.getValue("straight_m").jsonPrimitive.content.toInt(),
        modePriority = transport.getValue("mode_priority").jsonArray.map { value ->
            JourneyMode.fromWire(value.jsonPrimitive.content)
        },
        legs = JourneyMode.entries.mapNotNull { mode ->
            transport[mode.wire]
                ?.takeUnless { it is JsonNull }
                ?.jsonObject
                ?.toJourneyLeg()
                ?.let { mode to it }
        }.toMap(),
    )
}

private fun JsonObject.toJourneyLeg(): JourneyLeg = JourneyLeg(
    status = JourneyRouteStatus.fromWire(getValue("status").jsonPrimitive.content),
    statusReason = stringOrNull("status_reason"),
    minutes = intOrNull("min"),
    meters = intOrNull("m"),
    source = getValue("source").jsonPrimitive.content,
    handoff = objectOrNull("handoff")?.let { handoff ->
        JourneyHandoff(
            naver = handoff.getValue("naver").jsonPrimitive.content,
            kakao = handoff.getValue("kakao").jsonPrimitive.content,
            tmap = handoff.getValue("tmap").jsonPrimitive.content,
        )
    },
)

private fun JsonObject.stringOrNull(key: String): String? =
    get(key)?.jsonPrimitive?.contentOrNull

private fun JsonObject.intOrNull(key: String): Int? =
    get(key)?.jsonPrimitive?.intOrNull

private fun JsonObject.objectOrNull(key: String): JsonObject? =
    get(key)?.takeUnless { it is JsonNull }?.jsonObject
