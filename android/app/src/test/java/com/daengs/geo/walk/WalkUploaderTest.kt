package com.daengs.geo.walk

import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WalkUploaderTest {

    @Test
    fun `sends start then batched fixes then finish`() = runTest {
        val api = RecordingApi()
        val log = FakeLog(session(ended = 9_000L), fixes = fixes(5))

        assertNotNull(uploader(api, log, batchSize = 2).upload(SESSION))

        assertEquals(
            listOf("start:$SESSION:halmae:1000", "fixes:2", "fixes:2", "fixes:1", "finish:9000"),
            api.calls,
        )
    }

    @Test
    fun `uploads every fix exactly once across batches`() = runTest {
        val api = RecordingApi()
        val log = FakeLog(session(ended = 9_000L), fixes = fixes(7))

        uploader(api, log, batchSize = 3).upload(SESSION)

        assertEquals((0..6).toList(), api.sentSequences)
    }

    /** 서버 `FixBatchIn.fixes` 상한과 같아야 한다. 넘기면 배치 하나가 통째로 422 다. */
    @Test
    fun `default batch size matches the server cap`() {
        assertEquals(2000, WalkUploader.MAX_BATCH)
    }

    @Test
    fun `blank dog id disables upload entirely`() = runTest {
        val api = RecordingApi()
        val log = FakeLog(session(ended = 9_000L), fixes = fixes(3))
        val uploader = WalkUploader(api, log, dogId = "")

        assertFalse(uploader.enabled)
        assertNull(uploader.upload(SESSION))
        assertTrue(api.calls.isEmpty())
    }

    /** 프로세스 사망으로 안 닫힌 세션. finish 를 지어내지 않는다 — 끝난 시각을 모른다. */
    @Test
    fun `an unfinished session is not uploaded`() = runTest {
        val api = RecordingApi()
        val log = FakeLog(session(ended = null), fixes = fixes(3))

        assertNull(uploader(api, log).upload(SESSION))
        assertTrue(api.calls.isEmpty())
    }

    @Test
    fun `an unknown or empty session is not uploaded`() = runTest {
        val api = RecordingApi()

        assertNull(uploader(api, FakeLog(null, emptyList())).upload(SESSION))
        assertNull(uploader(api, FakeLog(session(ended = 9_000L), emptyList())).upload(SESSION))
        assertTrue(api.calls.isEmpty())
    }

    /** 실패해도 로컬 원본은 남는다 — 서버가 purge 한 뒤 유일한 사본이다. */
    @Test
    fun `a failed upload leaves the local rows alone`() = runTest {
        val log = FakeLog(session(ended = 9_000L), fixes = fixes(3))
        val api = RecordingApi(failOnFinish = true)

        runCatching { uploader(api, log).upload(SESSION) }

        assertEquals(3, log.fixes(SESSION).size)
        assertTrue(log.deleted.isEmpty())
    }

    // ------------------------------------------------------------------ helpers

    private fun uploader(api: WalkApi, log: WalkFixLog, batchSize: Int = 100) =
        WalkUploader(api, log, dogId = DOG, batchSize = batchSize)

    private fun session(ended: Long?) =
        RecordedSession(SESSION, DOG, startedAtMillis = 1_000L, endedAtMillis = ended)

    private fun fixes(count: Int) = (0 until count).map {
        RecordedFix(
            clientSeq = it, chainIndex = 0, atMillis = 1_000L + it * 5_000L,
            lat = 37.4979, lng = 127.0276, accuracyM = 8f, isMock = false,
        )
    }

    private class RecordingApi(private val failOnFinish: Boolean = false) : WalkApi {
        val calls = mutableListOf<String>()
        val sentSequences = mutableListOf<Int>()

        override suspend fun startSession(sessionId: String, dogId: String, startedAtMillis: Long) {
            calls += "start:$sessionId:$dogId:$startedAtMillis"
        }

        override suspend fun uploadFixes(sessionId: String, fixes: List<RecordedFix>): FixBatchResult {
            calls += "fixes:${fixes.size}"
            sentSequences += fixes.map { it.clientSeq }
            return FixBatchResult(stored = fixes.size, duplicates = 0, fixCount = sentSequences.size)
        }

        override suspend fun finishSession(sessionId: String, endedAtMillis: Long) =
            if (failOnFinish) throw WalkApiException(500, "boom")
            else kotlinx.serialization.json.JsonObject(emptyMap())
                .also { calls += "finish:$endedAtMillis" }
    }

    private class FakeLog(
        private val stored: RecordedSession?,
        private val fixes: List<RecordedFix>,
    ) : WalkFixLog {
        val deleted = mutableListOf<String>()

        override suspend fun openSession(session: RecordedSession) = Unit
        override suspend fun append(sessionId: String, fix: RecordedFix) = Unit
        override suspend fun closeSession(sessionId: String, endedAtMillis: Long) = Unit
        override suspend fun deleteSession(sessionId: String) { deleted += sessionId }
        override suspend fun unfinishedSessions(): List<RecordedSession> = emptyList()
        override suspend fun session(sessionId: String): RecordedSession? =
            stored?.takeIf { it.id == sessionId }

        override suspend fun fixes(sessionId: String): List<RecordedFix> = fixes
    }

    private companion object {
        const val SESSION = "walk-1"
        const val DOG = "halmae"
    }
}
