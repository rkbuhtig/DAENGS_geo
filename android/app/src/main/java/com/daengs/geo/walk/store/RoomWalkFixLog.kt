package com.daengs.geo.walk.store

import com.daengs.geo.walk.RecordedFix
import com.daengs.geo.walk.RecordedSession
import com.daengs.geo.walk.WalkFixLog

class RoomWalkFixLog(private val dao: WalkDao) : WalkFixLog {
    override suspend fun openSession(session: RecordedSession) = dao.insertSession(
        WalkSessionRow(
            id = session.id,
            dogId = session.dogId,
            startedAtMillis = session.startedAtMillis,
            endedAtMillis = session.endedAtMillis,
        ),
    )

    override suspend fun append(sessionId: String, fix: RecordedFix) = dao.insertFix(
        WalkFixRow(
            sessionId = sessionId,
            clientSeq = fix.clientSeq,
            atMillis = fix.atMillis,
            lat = fix.lat,
            lng = fix.lng,
            accuracyM = fix.accuracyM,
            isMock = fix.isMock,
        ),
    )

    override suspend fun closeSession(sessionId: String, endedAtMillis: Long) =
        dao.closeSession(sessionId, endedAtMillis)

    override suspend fun unfinishedSessions(): List<RecordedSession> =
        dao.unfinishedSessions().map {
            RecordedSession(it.id, it.dogId, it.startedAtMillis, it.endedAtMillis)
        }

    override suspend fun fixes(sessionId: String): List<RecordedFix> = dao.fixes(sessionId).map {
        RecordedFix(it.clientSeq, it.atMillis, it.lat, it.lng, it.accuracyM, it.isMock)
    }
}
