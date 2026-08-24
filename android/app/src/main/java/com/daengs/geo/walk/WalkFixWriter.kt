package com.daengs.geo.walk

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlin.coroutines.cancellation.CancellationException

/**
 * The only writer into [WalkFixLog], for two reasons.
 *
 * Ordering: commands run one at a time in submission order, so a fix can never reach storage
 * before the session row it belongs to.
 *
 * Lifetime: the scope is the application's, not the service's. `stopRecording()` calls `stopSelf()`
 * right after queueing the final write, and a service-scoped coroutine would be cancelled before
 * that write landed.
 */
class WalkFixWriter(
    private val log: WalkFixLog,
    scope: CoroutineScope,
) {
    private val commands = Channel<suspend () -> Unit>(Channel.UNLIMITED)

    private val _failure = MutableStateFlow<String?>(null)

    /** Latest write failure. Storage failing is not a reason to stop location collection. */
    val failure: StateFlow<String?> = _failure.asStateFlow()

    init {
        scope.launch {
            for (command in commands) {
                try {
                    command()
                } catch (cancellation: CancellationException) {
                    throw cancellation
                } catch (error: Throwable) {
                    _failure.value = error.message ?: "산책 기록을 저장하지 못했습니다."
                }
            }
        }
    }

    fun openSession(session: RecordedSession) = enqueue { log.openSession(session) }

    fun append(sessionId: String, fix: RecordedFix) = enqueue { log.append(sessionId, fix) }

    fun closeSession(sessionId: String, endedAtMillis: Long) =
        enqueue { log.closeSession(sessionId, endedAtMillis) }

    fun deleteSession(sessionId: String) = enqueue { log.deleteSession(sessionId) }

    /** Waits until every command submitted before this call has completed (successfully or not). */
    suspend fun flush() {
        val barrier = CompletableDeferred<Unit>()
        enqueue { barrier.complete(Unit) }
        barrier.await()
    }

    fun clearFailure() {
        _failure.value = null
    }

    private fun enqueue(command: suspend () -> Unit) {
        check(commands.trySend(command).isSuccess) { "walk fix writer is unavailable" }
    }
}
