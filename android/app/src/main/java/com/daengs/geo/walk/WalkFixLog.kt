package com.daengs.geo.walk

/**
 * Durable record of what the device actually reported during a walk.
 *
 * It stores **raw fixes, before TrailRecorder filtering**. The recorder drops jitter and poor
 * accuracy so the drawn line stays clean, but those thresholds are provisional and will move once
 * real-device measurements land. Persisting the recorder's output instead would bake today's
 * thresholds into every past walk and make them unrecomputable.
 *
 * Field names mirror the server contract (docs/contracts/walk-record.md). Whether walks are ever
 * uploaded is undecided; keeping the shape aligned means that decision stays a replay of stored
 * rows rather than a translation.
 */
interface WalkFixLog {
    /** Idempotent: re-opening a known session id keeps the original start. */
    suspend fun openSession(session: RecordedSession)

    suspend fun append(sessionId: String, fix: RecordedFix)

    suspend fun closeSession(sessionId: String, endedAtMillis: Long)

    /**
     * Sessions that never got a close. A walk ends this way when the process dies or the user
     * force-stops the app, and the stored fixes are the only evidence that walk happened.
     */
    suspend fun unfinishedSessions(): List<RecordedSession>

    suspend fun fixes(sessionId: String): List<RecordedFix>
}

data class RecordedSession(
    val id: String,
    /** Null until the app consumes a dog profile — this repo does not own one (decision #4). */
    val dogId: String?,
    val startedAtMillis: Long,
    val endedAtMillis: Long? = null,
)

/** One reported position, field for field with the server `WalkFix` contract. */
data class RecordedFix(
    val clientSeq: Int,
    val atMillis: Long,
    val lat: Double,
    val lng: Double,
    val accuracyM: Float?,
    val isMock: Boolean,
)
