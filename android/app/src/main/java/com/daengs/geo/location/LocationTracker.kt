package com.daengs.geo.location

import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * What the current subscription is doing. A feed can end in two ways that the UI must tell
 * apart: a finite source (replay) running out, and a source failing. Both used to be silent —
 * failure crashed the process, completion froze the app on a dead feed.
 */
sealed interface FeedStatus {
    data object Idle : FeedStatus

    data object Running : FeedStatus

    data object Completed : FeedStatus

    data class Failed(val cause: Throwable) : FeedStatus
}

/** Owns the app's single continuous location subscription. */
class LocationTracker(
    private val scope: CoroutineScope,
) {
    private val _updates = MutableSharedFlow<LocationSample>(extraBufferCapacity = 16)
    val updates = _updates.asSharedFlow()

    private val _status = MutableStateFlow<FeedStatus>(FeedStatus.Idle)
    val status: StateFlow<FeedStatus> = _status.asStateFlow()

    private var collectionJob: Job? = null
    private var generation = 0

    fun start(
        source: LocationSource,
        config: LocationUpdateConfig = LocationUpdateConfig(),
    ) {
        collectionJob?.cancel()
        val token = ++generation
        _status.value = FeedStatus.Running
        collectionJob = scope.launch {
            try {
                source.locationUpdates(config).collect(_updates::emit)
                if (generation == token) _status.value = FeedStatus.Completed
            } catch (cancellation: CancellationException) {
                throw cancellation
            } catch (error: Throwable) {
                // The feed is the only owner of this failure: nothing above collect() can catch it,
                // and an uncaught throw here takes the process down.
                if (generation == token) _status.value = FeedStatus.Failed(error)
            }
        }
    }

    fun stop() {
        collectionJob?.cancel()
        collectionJob = null
        generation++
        _status.value = FeedStatus.Idle
    }
}
