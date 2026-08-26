package com.daengs.geo.hospital

import java.net.HttpURLConnection
import java.net.URL
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject

/**
 * `baseUrl` 은 값이 아니라 **함수**다. 주소는 실행 중에 바뀔 수 있고(ServerAddress), 그때
 * 이미 만들어진 API 객체가 옛 주소를 붙들고 있으면 앱을 다시 켜야 반영된다.
 */
class HospitalApi(
    private val baseUrl: () -> String,
    private val json: Json = Json,
) {
    private val endpoint: String get() = "${baseUrl().trimEnd('/')}/hospital/search"

    suspend fun search(payload: JsonObject): HospitalSearchResponse = withContext(Dispatchers.IO) {
        val connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 10_000
            readTimeout = 20_000
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("Accept", "application/json")
        }

        try {
            connection.outputStream.bufferedWriter(Charsets.UTF_8).use { writer ->
                writer.write(payload.toString())
            }
            val status = connection.responseCode
            val body = (if (status in 200..299) connection.inputStream else connection.errorStream)
                ?.bufferedReader(Charsets.UTF_8)
                ?.use { it.readText() }
                .orEmpty()
            if (status !in 200..299) {
                throw HospitalApiException(status, body.take(500))
            }
            json.parseToJsonElement(body).jsonObject.toHospitalSearchResponse()
        } finally {
            connection.disconnect()
        }
    }
}

class HospitalApiException(status: Int, body: String) :
    IllegalStateException("Hospital search failed ($status): $body")

class HospitalRepository(private val api: HospitalApi) {
    suspend fun search(payload: JsonObject): HospitalSearchResponse = api.search(payload)
}
