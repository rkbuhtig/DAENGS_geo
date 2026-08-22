package com.daengs.geo.location

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch

/** Owns the app's single continuous location subscription. */
class LocationTracker(
    private val scope: CoroutineScope,
) {
    private val _updates = MutableSharedFlow<LocationSample>(extraBufferCapacity = 16)
    val updates = _updates.asSharedFlow()

    private var collectionJob: Job? = null

    fun start(
        source: LocationSource,
        config: LocationUpdateConfig = LocationUpdateConfig(),
    ) {
        collectionJob?.cancel()
        collectionJob = scope.launch {
            source.locationUpdates(config).collect(_updates::emit)
        }
    }

    fun stop() {
        collectionJob?.cancel()
        collectionJob = null
    }
}
