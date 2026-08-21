package com.daengs.geo.hospital

import com.daengs.geo.location.GeoPoint
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

enum class LocationMode { FOLLOW_DEVICE, PINNED }

data class SearchSession(
    val state: JsonObject?,
    val deviceLocation: GeoPoint?,
    val mode: LocationMode,
)

object SearchRequestBuilder {
    fun build(
        session: SearchSession,
        edits: JsonArray = JsonArray(emptyList()),
        utterance: String? = null,
    ): JsonObject {
        require(session.state != null || session.deviceLocation != null) {
            "The first search requires a device location"
        }
        require(session.mode != LocationMode.PINNED || session.state != null) {
            "Pinned search requires server state"
        }

        return buildJsonObject {
            session.state?.let { put("state", it) }
            if (session.mode == LocationMode.FOLLOW_DEVICE) {
                session.deviceLocation?.let { point ->
                    put("origin", buildJsonArray {
                        add(JsonPrimitive(point.latitude))
                        add(JsonPrimitive(point.longitude))
                    })
                }
            }
            put("edits", edits)
            utterance?.takeIf { it.isNotBlank() }?.let { put("utterance", it) }
            put("transport", "estimate")
            put("companion", "dog")
            put("with_evidence", true)
        }
    }

    fun setOriginEdit(point: GeoPoint): JsonArray = buildJsonArray {
        add(buildJsonObject {
            put("tool", "set_origin")
            put("args", buildJsonObject {
                put("lat", point.latitude)
                put("lng", point.longitude)
            })
        })
    }

    fun setRadiusEdit(meters: Int): JsonArray = buildJsonArray {
        add(buildJsonObject {
            put("tool", "set_radius")
            put("args", buildJsonObject { put("m", meters) })
        })
    }
}
