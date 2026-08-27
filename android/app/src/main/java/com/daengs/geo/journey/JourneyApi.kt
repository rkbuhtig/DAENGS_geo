package com.daengs.geo.journey

import java.net.HttpURLConnection
import java.net.URL
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject

class JourneyApi(
    private val baseUrl: () -> String,
    private val json: Json = Json,
) {
    private val endpoint: String get() = "${baseUrl().trimEnd('/')}/journey"

    suspend fun load(request: PlaceJourneyRequest): JourneyResponse =
        withContext(Dispatchers.IO) {
            val connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 10_000
                readTimeout = 30_000
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                setRequestProperty("Accept", "application/json")
            }
            try {
                connection.outputStream.bufferedWriter(Charsets.UTF_8).use { writer ->
                    writer.write(request.toJson().toString())
                }
                val status = connection.responseCode
                val body = (if (status in 200..299) connection.inputStream else connection.errorStream)
                    ?.bufferedReader(Charsets.UTF_8)
                    ?.use { it.readText() }
                    .orEmpty()
                if (status !in 200..299) throw JourneyApiException(status, body.take(500))
                json.parseToJsonElement(body).jsonObject.toJourneyResponse()
            } finally {
                connection.disconnect()
            }
        }
}

class JourneyApiException(status: Int, body: String) :
    IllegalStateException("Journey request failed ($status): $body")
