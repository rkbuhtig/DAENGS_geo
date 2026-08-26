package com.daengs.geo.walk

import java.io.File
import java.time.Instant
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.add
import kotlinx.serialization.json.put

/**
 * Writes one finished session — meta plus every raw fix — to a JSON file for development handoff.
 *
 * **Why a file, when the uploader already sends the session**: the server purges raw fixes at
 * finish, so after upload the Room rows on this device are the only copy of the trajectory.
 * Debugging a wrong distance or a missed encounter needs exactly those rows, off the device,
 * in a folder the developer chooses. `scripts/verify/walk_bundle.py` pulls these files over adb and
 * can replay them against a local server — the export format is therefore **field for field the
 * server wire contract** (`at` as ISO-8601, `client_seq`, `chain_index`, …), so a bundle can be
 * POSTed back without translation.
 *
 * Debug builds only — the caller gates on [com.daengs.geo.BuildConfig.DEBUG]. This class stays
 * unconditional so a JVM test can drive it with a plain temp directory.
 */
class WalkSessionExporter(
    private val log: WalkFixLog,
    private val directory: File,
) {
    /** Returns the written file, or null when the session is unknown, still open, or empty. */
    suspend fun export(sessionId: String): File? {
        val session = log.session(sessionId) ?: return null
        if (session.endedAtMillis == null) return null
        val fixes = log.fixes(sessionId)
        if (fixes.isEmpty()) return null

        val payload = buildJsonObject {
            put("format", FORMAT)
            put("session", buildJsonObject {
                put("id", session.id)
                put("dog_id", session.dogId)          // null 그대로 — 지어내지 않는다 (결정 #58)
                put("started_at", iso(session.startedAtMillis))
                put("ended_at", iso(session.endedAtMillis))
            })
            put("fixes", buildJsonArray {
                fixes.forEach { fix ->
                    add(buildJsonObject {
                        put("client_seq", fix.clientSeq)
                        put("chain_index", fix.chainIndex)
                        put("at", iso(fix.atMillis))
                        put("lat", fix.lat)
                        put("lng", fix.lng)
                        put("accuracy_m", fix.accuracyM)
                        put("is_mock", fix.isMock)
                    })
                }
            })
        }

        directory.mkdirs()
        // 시작 시각이 앞에 와서 이름순 = 시간순. id 조각은 충돌 방지용이다.
        val file = File(directory, "walk-${session.startedAtMillis}-${session.id.take(8)}.json")
        file.writeText(payload.toString())
        return file
    }

    private fun iso(millis: Long): String = Instant.ofEpochMilli(millis).toString()

    companion object {
        const val FORMAT = 1
        /** Under the app's internal files dir — readable via `adb  run-as` on debug builds. */
        const val DIRECTORY = "walk-exports"
    }
}
