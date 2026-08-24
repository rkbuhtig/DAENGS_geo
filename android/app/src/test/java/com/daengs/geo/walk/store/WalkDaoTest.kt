package com.daengs.geo.walk.store

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.daengs.geo.walk.RecordedFix
import com.daengs.geo.walk.RecordedSession
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Runs the real Room/SQLite stack in the JVM. What is asserted here is storage behaviour, not mapping. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class WalkDaoTest {
    private lateinit var db: DaengsDatabase
    private lateinit var log: RoomWalkFixLog

    @Before
    fun setUp() {
        db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(),
            DaengsDatabase::class.java,
        ).build()
        log = RoomWalkFixLog(db.walkDao())
    }

    @After
    fun tearDown() = db.close()

    @Test
    fun `fixes survive as written and come back in client order`() = runBlocking {
        log.openSession(session("s1"))
        log.append("s1", fix(1, lat = 37.1))
        log.append("s1", fix(0, lat = 37.0))

        val stored = log.fixes("s1")

        assertEquals(listOf(0, 1), stored.map { it.clientSeq })
        assertEquals(37.0, stored.first().lat, 1e-9)
        assertEquals(5f, stored.first().accuracyM)
    }

    @Test
    fun `re-sending the same clientSeq is a no-op, not a duplicate`() = runBlocking {
        log.openSession(session("s1"))
        log.append("s1", fix(0, lat = 37.0))
        log.append("s1", fix(0, lat = 38.0))

        val stored = log.fixes("s1")

        assertEquals(1, stored.size)
        assertEquals(37.0, stored.single().lat, 1e-9)
    }

    @Test
    fun `re-opening a known session keeps the original start`() = runBlocking {
        log.openSession(RecordedSession("s1", dogId = null, startedAtMillis = 100L))
        log.openSession(RecordedSession("s1", dogId = null, startedAtMillis = 999L))

        assertEquals(100L, log.unfinishedSessions().single().startedAtMillis)
    }

    @Test
    fun `a session without a close stays recoverable and its fixes stay readable`() = runBlocking {
        log.openSession(session("open"))
        log.append("open", fix(0))
        log.openSession(session("done"))
        log.closeSession("done", endedAtMillis = 500L)

        val unfinished = log.unfinishedSessions()

        assertEquals(listOf("open"), unfinished.map { it.id })
        assertEquals(1, log.fixes("open").size)
    }

    @Test
    fun `closing twice does not move the end time`() = runBlocking {
        log.openSession(session("s1"))
        log.closeSession("s1", endedAtMillis = 500L)
        log.closeSession("s1", endedAtMillis = 900L)

        assertTrue(log.unfinishedSessions().isEmpty())
        assertEquals(500L, db.walkDao().session("s1")?.endedAtMillis)
    }

    private fun session(id: String) = RecordedSession(id, dogId = null, startedAtMillis = 0L)

    private fun fix(seq: Int, lat: Double = 37.0) = RecordedFix(
        clientSeq = seq,
        atMillis = seq.toLong(),
        lat = lat,
        lng = 127.0,
        accuracyM = 5f,
        isMock = false,
    )
}
