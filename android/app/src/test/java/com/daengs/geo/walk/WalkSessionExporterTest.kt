package com.daengs.geo.walk

import java.io.File
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/**
 * The export file is the handoff copy of the only surviving trajectory, so what matters is:
 * it exists exactly for finished non-empty sessions, and its fields match the server wire
 * contract so `scripts/verify/walk_bundle.py` can POST it back without translation.
 */
class WalkSessionExporterTest {

    @get:Rule
    val folder = TemporaryFolder()

    private class FakeLog(
        private val session: RecordedSession?,
        private val fixes: List<RecordedFix>,
    ) : WalkFixLog {
        override suspend fun openSession(session: RecordedSession) = error("unused")
        override suspend fun append(sessionId: String, fix: RecordedFix) = error("unused")
        override suspend fun closeSession(sessionId: String, endedAtMillis: Long) = error("unused")
        override suspend fun deleteSession(sessionId: String) = error("unused")
        override suspend fun unfinishedSessions(): List<RecordedSession> = error("unused")
        override suspend fun session(sessionId: String): RecordedSession? = session
        override suspend fun fixes(sessionId: String): List<RecordedFix> = fixes
    }

    private fun fix(seq: Int) = RecordedFix(
        clientSeq = seq, chainIndex = 0, atMillis = 1_756_000_000_000 + seq * 5_000L,
        lat = 37.5, lng = 127.0, accuracyM = 8.0f, isMock = false,
    )

    @Test
    fun `a finished session exports the server wire contract`() = runTest {
        val log = FakeLog(
            RecordedSession("s-1", dogId = "halmae",
                            startedAtMillis = 1_756_000_000_000, endedAtMillis = 1_756_000_060_000),
            listOf(fix(0), fix(1)),
        )
        val file = WalkSessionExporter(log, folder.root).export("s-1")!!

        val payload = Json.parseToJsonElement(file.readText()).jsonObject
        val session = payload["session"]!!.jsonObject
        assertEquals("s-1", session["id"]!!.jsonPrimitive.content)
        assertEquals("halmae", session["dog_id"]!!.jsonPrimitive.content)
        assertEquals("2025-08-24T01:46:40Z", session["started_at"]!!.jsonPrimitive.content)

        val first = payload["fixes"]!!.jsonArray[0].jsonObject
        // 서버 FixBatchIn 이 받는 키 그대로 — 번역 없이 POST 가능해야 한다.
        assertEquals(setOf("client_seq", "chain_index", "at", "lat", "lng", "accuracy_m", "is_mock"),
                     first.keys)
        assertTrue(first["at"]!!.jsonPrimitive.content.endsWith("Z"))
    }

    @Test
    fun `an open or empty session exports nothing`() = runTest {
        val open = FakeLog(
            RecordedSession("s-2", null, 1_756_000_000_000, endedAtMillis = null), listOf(fix(0)),
        )
        assertNull(WalkSessionExporter(open, folder.root).export("s-2"))

        val empty = FakeLog(
            RecordedSession("s-3", null, 1_756_000_000_000, 1_756_000_060_000), emptyList(),
        )
        assertNull(WalkSessionExporter(empty, folder.root).export("s-3"))
    }

    @Test
    fun `file names sort by start time`() = runTest {
        val log = FakeLog(
            RecordedSession("abcdefgh-rest", "halmae", 1_756_000_000_000, 1_756_000_060_000),
            listOf(fix(0)),
        )
        val file = WalkSessionExporter(log, folder.root).export("x")!!
        assertEquals("walk-1756000000000-abcdefgh.json", file.name)
    }
}
