package com.daengs.geo.walk

import android.content.Context
import androidx.core.content.ContextCompat
import kotlinx.coroutines.flow.StateFlow

class ForegroundWalkTrackingController(
    context: Context,
    private val store: WalkTrackingStore,
) : WalkTrackingController {
    private val appContext = context.applicationContext

    override val state: StateFlow<WalkTrackingState> = store.state

    override fun start() {
        ContextCompat.startForegroundService(
            appContext,
            WalkTrackingService.commandIntent(appContext, WalkTrackingService.ACTION_START),
        )
    }

    override fun pause() {
        appContext.startService(
            WalkTrackingService.commandIntent(appContext, WalkTrackingService.ACTION_PAUSE),
        )
    }

    override fun resume() {
        appContext.startService(
            WalkTrackingService.commandIntent(appContext, WalkTrackingService.ACTION_RESUME),
        )
    }

    override fun stop() {
        appContext.startService(
            WalkTrackingService.commandIntent(appContext, WalkTrackingService.ACTION_STOP),
        )
    }
}
