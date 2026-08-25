package com.daengs.geo.walk

import kotlinx.serialization.json.JsonObject

/**
 * Sends one finished walk to the server: start → fixes → finish.
 *
 * **Resend everything, track nothing.** There is no per-fix upload cursor and no `syncState`
 * column, because both sides already collapse repeats — Room keys fixes by `(sessionId,
 * clientSeq)` with INSERT IGNORE, and the server counts a replayed `client_seq` as a duplicate.
 * A retry is therefore just "run it again from the top". Storing progress would add a schema and
 * a class of bugs (a cursor that disagrees with what actually landed) to buy nothing.
 *
 * **Explicit stop only.** Nothing is uploaded while a walk is in progress. The server's product
 * output — WalkFacts, facility encounters — only exists after `finish`, so streaming coordinates
 * during the walk would buy no product capability while leaving raw positions on the server for
 * the whole walk if the process dies. Collecting to Room and uploading once shrinks that exposure
 * to the few seconds of the upload itself.
 *
 * **Gated by the identifier, twice.** [dogId] is what this build was given (decision #58) and
 * blank means this build never uploads. What actually goes on the wire is the session's own
 * `dogId`, written when the walk started — a walk belongs to the dog it was recorded under, not
 * to whatever the build happens to be configured with by the time it uploads.
 */
class WalkUploader(
    private val api: WalkApi,
    private val log: WalkFixLog,
    private val dogId: String,
    private val batchSize: Int = MAX_BATCH,
) {
    val enabled: Boolean get() = dogId.isNotBlank()

    /**
     * Uploads one closed session. Returns null when the walk is not uploadable (disabled, unknown,
     * still open, or empty) and throws when the network or server rejected it — the caller decides
     * whether a failure is worth surfacing. The local rows are never deleted here: they are the
     * only copy that survives the server-side purge, and deleting them is a retention decision,
     * not this class's call.
     */
    suspend fun upload(sessionId: String): WalkUploadResult? {
        if (!enabled) return null
        val session = log.session(sessionId) ?: return null
        val endedAtMillis = session.endedAtMillis ?: return null   // 열린 세션은 finish 할 수 없다
        // 이 산책이 녹화될 때의 주인. 빌드 값이 그 뒤에 바뀌었어도 사실의 귀속은 안 바뀐다.
        val subject = session.dogId?.takeIf { it.isNotBlank() } ?: return null

        val fixes = log.fixes(sessionId)
        if (fixes.isEmpty()) return null

        api.startSession(sessionId, subject, session.startedAtMillis)
        var stored = 0
        var duplicates = 0
        fixes.chunked(batchSize).forEach { batch ->
            val result = api.uploadFixes(sessionId, batch)
            stored += result.stored
            duplicates += result.duplicates
        }
        val finished = api.finishSession(sessionId, endedAtMillis)
        return WalkUploadResult(fixes.size, stored, duplicates, finished)
    }

    companion object {
        /** Server-side `FixBatchIn.fixes` cap. Splitting here keeps a long walk from 422-ing. */
        const val MAX_BATCH = 2000
    }
}

/** What one upload actually moved. The server's own `finish` response rides along in [facts]. */
data class WalkUploadResult(
    val fixCount: Int,
    val stored: Int,
    val duplicates: Int,
    val facts: JsonObject,
)
