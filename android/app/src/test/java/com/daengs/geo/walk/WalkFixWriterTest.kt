package com.daengs.geo.walk

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class WalkFixWriterTest {
    @Test
    fun `commands land in submission order, so a fix cannot outrun its session row`() {
        val log = RecordingLog()

        withWriter(log) { writer ->
            writer.openSession(session("s1"))
            writer.append("s1", fix(0))
            writer.append("s1", fix(1))
            writer.closeSession("s1", 100L)
        }

        assertEquals(listOf("open:s1", "append:0", "append:1", "close:s1"), log.calls)
    }

    @Test
    fun `a failed write is reported and does not stop later writes`() {
        val log = RecordingLog(failOnSeq = 0)
        var reported: String? = null

        withWriter(log) { writer ->
            writer.openSession(session("s1"))
            writer.append("s1", fix(0))
            writer.append("s1", fix(1))
            reported = writer.failure.value
        }

        assertNotNull(reported)
        assertEquals(listOf("open:s1", "append:1"), log.calls)
    }

    @Test
    fun `no failure is reported when every write lands`() {
        val log = RecordingLog()
        var reported: String? = "unset"

        withWriter(log) { writer ->
            writer.openSession(session("s1"))
            writer.append("s1", fix(0))
            reported = writer.failure.value
        }

        assertNull(reported)
    }

    /** Unconfined so each queued command runs at submission — no scheduler advancing in asserts. */
    private fun withWriter(log: WalkFixLog, block: (WalkFixWriter) -> Unit) {
        val scope = CoroutineScope(UnconfinedTestDispatcher())
        try {
            block(WalkFixWriter(log, scope))
        } finally {
            scope.cancel()
        }
    }

    private fun session(id: String) = RecordedSession(id = id, dogId = null, startedAtMillis = 0L)

    private fun fix(seq: Int) = RecordedFix(
        clientSeq = seq,
        atMillis = seq.toLong(),
        lat = 37.0,
        lng = 127.0,
        accuracyM = 5f,
        isMock = false,
    )

    private class RecordingLog(private val failOnSeq: Int? = null) : WalkFixLog {
        val calls = mutableListOf<String>()

        override suspend fun openSession(session: RecordedSession) {
            calls += "open:${session.id}"
        }

        override suspend fun append(sessionId: String, fix: RecordedFix) {
            if (fix.clientSeq == failOnSeq) error("disk full")
            calls += "append:${fix.clientSeq}"
        }

        override suspend fun closeSession(sessionId: String, endedAtMillis: Long) {
            calls += "close:$sessionId"
        }

        override suspend fun unfinishedSessions(): List<RecordedSession> = emptyList()

        override suspend fun fixes(sessionId: String): List<RecordedFix> = emptyList()
    }
}
