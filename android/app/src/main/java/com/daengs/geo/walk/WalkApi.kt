package com.daengs.geo.walk

import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

/**
 * The walk collection endpoints. Same shape as [com.daengs.geo.hospital.HospitalApi] — a plain
 * HttpURLConnection, no new dependency.
 *
 * Every call here is idempotent on the server: re-opening a session id keeps the original start,
 * a replayed `client_seq` collapses into a duplicate count, and finishing twice returns the facts
 * already derived. That is what lets the uploader retry by resending everything instead of
 * tracking how far it got.
 */
interface WalkApi {
    /** Idempotent. Re-sending a known id returns the stored session rather than restarting it. */
    suspend fun startSession(sessionId: String, dogId: String, startedAtMillis: Long)

    /** Returns how many rows were new; the rest were already stored under the same client_seq. */
    suspend fun uploadFixes(sessionId: String, fixes: List<RecordedFix>): FixBatchResult

    /**
     * Derives WalkFacts and facility encounters, then deletes the raw fixes server-side.
     * Idempotent — a second call returns the facts already derived instead of recomputing.
     */
    suspend fun finishSession(sessionId: String, endedAtMillis: Long): JsonObject
}

/**
 * 주소는 **생성 시점에 고정**된다. 산책 업로드는 `start → fixes… → finish` 가 한 덩어리라
 * 그 사이에 주소가 바뀌면 앞뒤가 다른 서버로 갈라진다 — 뒤 서버엔 그 세션이 없다.
 * 새 주소는 `WalkUploader` 가 **다음 업로드를 시작할 때** 새 인스턴스로 집어온다.
 */
class HttpWalkApi(
    baseUrl: String,
    private val json: Json = Json,
) : WalkApi {
    private val root = "${baseUrl.trimEnd('/')}/walk/sessions"

    override suspend fun startSession(sessionId: String, dogId: String, startedAtMillis: Long) {
        post(root, buildJsonObject {
            put("id", sessionId)
            put("dog_id", dogId)
            put("started_at", iso(startedAtMillis))
        })
    }

    override suspend fun uploadFixes(sessionId: String, fixes: List<RecordedFix>): FixBatchResult {
        val body = buildJsonObject {
            put("fixes", buildJsonArray {
                fixes.forEach { fix ->
                    add(buildJsonObject {
                        put("client_seq", fix.clientSeq)
                        put("chain_index", fix.chainIndex)
                        put("at", iso(fix.atMillis))
                        put("lat", fix.lat)
                        put("lng", fix.lng)
                        fix.accuracyM?.let { put("accuracy_m", it) }
                        put("is_mock", fix.isMock)
                    })
                }
            })
        }
        val response = post("$root/$sessionId/fixes", body)
        return FixBatchResult(
            stored = response["stored"]?.jsonPrimitive?.int ?: 0,
            duplicates = response["duplicates"]?.jsonPrimitive?.int ?: 0,
            fixCount = response["fix_count"]?.jsonPrimitive?.int ?: 0,
        )
    }

    override suspend fun finishSession(sessionId: String, endedAtMillis: Long): JsonObject =
        post("$root/$sessionId/finish", buildJsonObject { put("ended_at", iso(endedAtMillis)) })

    private fun iso(millis: Long): String = Instant.ofEpochMilli(millis).toString()

    private suspend fun post(url: String, payload: JsonObject): JsonObject =
        withContext(Dispatchers.IO) {
            val connection = (URL(url).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 10_000
                readTimeout = 30_000
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                setRequestProperty("Accept", "application/json")
            }
            try {
                connection.outputStream.bufferedWriter(Charsets.UTF_8).use { it.write(payload.toString()) }
                val status = connection.responseCode
                val body = (if (status in 200..299) connection.inputStream else connection.errorStream)
                    ?.bufferedReader(Charsets.UTF_8)
                    ?.use { it.readText() }
                    .orEmpty()
                if (status !in 200..299) {
                    throw WalkApiException(status, body.take(500))
                }
                json.parseToJsonElement(body).jsonObject
            } finally {
                connection.disconnect()
            }
        }
}

data class FixBatchResult(val stored: Int, val duplicates: Int, val fixCount: Int)

class WalkApiException(val status: Int, body: String) :
    IllegalStateException("Walk upload failed ($status): $body")
