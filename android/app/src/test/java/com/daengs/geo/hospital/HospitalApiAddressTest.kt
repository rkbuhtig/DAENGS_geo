package com.daengs.geo.hospital

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.buildJsonObject
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 이 PR 의 핵심 주장을 지키는 테스트: **이미 만들어진 API 객체가 바뀐 주소를 쓴다.**
 *
 * `ServerAddressTest` 는 저장소가 맞는지만 본다 — `HospitalApi` 가 실수로 생성 시점에 URL 을
 * 붙들도록 되돌아가도 그 테스트는 전부 통과한다. 그래서 실제 요청이 어디로 가는지를 여기서 본다.
 *
 * 서버 둘을 띄우고 주소만 바꾼 뒤, 두 번째 요청이 **두 번째 서버**에 도착하는지 확인한다.
 */
class HospitalApiAddressTest {

    private class Stub {
        val hits = mutableListOf<String>()
        private val server: HttpServer = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        val base: String get() = "http://127.0.0.1:${server.address.port}"

        init {
            server.createContext("/hospital/search") { exchange ->
                hits += exchange.requestURI.path
                val body = """{"state":{},"results":[]}""".toByteArray()
                exchange.sendResponseHeaders(200, body.size.toLong())
                exchange.responseBody.use { it.write(body) }
            }
            server.start()
        }

        fun stop() = server.stop(0)
    }

    @Test
    fun `an existing api follows the address it is given at call time`() {
        val a = Stub()
        val b = Stub()
        var address = a.base
        val api = HospitalApi(baseUrl = { address })

        try {
            runBlocking { api.search(buildJsonObject { }) }
            assertEquals("첫 요청은 A 로 가야 한다", 1, a.hits.size)
            assertEquals(0, b.hits.size)

            address = b.base                      // 사용자가 서버 주소를 바꾼 순간
            runBlocking { api.search(buildJsonObject { }) }

            assertEquals("주소를 바꿨는데 여전히 A 로 갔다 — 생성 시점에 붙들고 있다", 1, a.hits.size)
            assertEquals("바뀐 주소가 다음 요청에 반영되지 않았다", 1, b.hits.size)
        } finally {
            a.stop()
            b.stop()
        }
    }
}
