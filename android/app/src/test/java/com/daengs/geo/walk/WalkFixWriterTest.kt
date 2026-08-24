package com.daengs.geo.walk

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.cancel
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
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

    @Test
    fun `flush waits for earlier writes instead of only queueing them`() = runTest {
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val log = RecordingLog(blockOnSeq = 0, entered = entered, release = release)
        val writer = WalkFixWriter(log, backgroundScope)

        writer.append("s1", fix(0))
        val flushing = async { writer.flush() }
        runCurrent()

        assertTrue(entered.isCompleted)
        assertFalse(flushing.isCompleted)
        release.complete(Unit)
        flushing.await()
        assertEquals(listOf("append:0"), log.calls)
    }

    @Test
    fun `failure can be cleared before a new recording`() {
        val log = RecordingLog(failOnSeq = 0)

        withWriter(log) { writer ->
            writer.append("s1", fix(0))
            assertNotNull(writer.failure.value)
            writer.clearFailure()
            assertNull(writer.failure.value)
        }
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
        chainIndex = 0,
        atMillis = seq.toLong(),
        lat = 37.0,
        lng = 127.0,
        accuracyM = 5f,
        isMock = false,
    )

    private class RecordingLog(
        private val failOnSeq: Int? = null,
        private val blockOnSeq: Int? = null,
        private val entered: CompletableDeferred<Unit>? = null,
        private val release: CompletableDeferred<Unit>? = null,
    ) : WalkFixLog {
        val calls = mutableListOf<String>()

        override suspend fun openSession(session: RecordedSession) {
            calls += "open:${session.id}"
        }

        override suspend fun append(sessionId: String, fix: RecordedFix) {
            if (fix.clientSeq == failOnSeq) error("disk full")
            if (fix.clientSeq == blockOnSeq) {
                entered?.complete(Unit)
                release?.await()
            }
            calls += "append:${fix.clientSeq}"
        }

        override suspend fun closeSession(sessionId: String, endedAtMillis: Long) {
            calls += "close:$sessionId"
        }

        override suspend fun deleteSession(sessionId: String) {
            calls += "delete:$sessionId"
        }

        override suspend fun unfinishedSessions(): List<RecordedSession> = emptyList()

        override suspend fun fixes(sessionId: String): List<RecordedFix> = emptyList()
    }
}
