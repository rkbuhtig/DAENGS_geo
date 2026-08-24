package com.daengs.geo.walk.store

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface WalkDao {
    /** IGNORE, not REPLACE: a repeated start must not rewrite the original startedAtMillis. */
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertSession(row: WalkSessionRow)

    /** IGNORE makes a replayed fix a no-op — the same guarantee the server gives on re-upload. */
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertFix(row: WalkFixRow)

    /**
     * Only closes an open session. Closing twice must not move the end time, and a late stop after
     * a recovery close must not overwrite the recovered one.
     */
    @Query(
        "UPDATE walk_session SET endedAtMillis = :endedAtMillis " +
            "WHERE id = :sessionId AND endedAtMillis IS NULL",
    )
    suspend fun closeSession(sessionId: String, endedAtMillis: Long)

    @Query("SELECT * FROM walk_session WHERE id = :sessionId")
    suspend fun session(sessionId: String): WalkSessionRow?

    @Query("SELECT * FROM walk_session WHERE endedAtMillis IS NULL ORDER BY startedAtMillis")
    suspend fun unfinishedSessions(): List<WalkSessionRow>

    @Query("SELECT * FROM walk_fix WHERE sessionId = :sessionId ORDER BY clientSeq")
    suspend fun fixes(sessionId: String): List<WalkFixRow>
}
