package com.daengs.geo.walk

import com.daengs.geo.location.LocationSample
import com.daengs.geo.map.layers.trail.TrailSnapshot
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

data class WalkTrackingState(
    val trail: TrailSnapshot = TrailSnapshot(),
    val lastSample: LocationSample? = null,
    val errorMessage: String? = null,
)

/**
 * UI-facing control surface. The Activity/ViewModel may ask for lifecycle transitions and observe
 * state, but it never owns the continuous location subscription or TrailRecorder.
 */
interface WalkTrackingController {
    val state: StateFlow<WalkTrackingState>

    fun start()

    fun pause()

    fun resume()

    fun stop()
}

/** Process-local bridge between the started service and UI observers. Persistence is a later step. */
class WalkTrackingStore {
    private val _state = MutableStateFlow(WalkTrackingState())
    val state: StateFlow<WalkTrackingState> = _state.asStateFlow()

    internal fun publish(state: WalkTrackingState) {
        _state.value = state
    }
}
