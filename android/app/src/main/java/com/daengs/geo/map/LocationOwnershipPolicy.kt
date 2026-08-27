package com.daengs.geo.map

import com.daengs.geo.walk.TrackingState

/** Whether the Activity that owns the screen feed is visible. */
internal enum class AppVisibility { FOREGROUND, BACKGROUND }

/** Exactly one component may own a continuous location subscription. */
internal enum class LocationOwner {
    NONE,
    SCREEN_DEVICE,
    SCREEN_REPLAY,
    WALK_SERVICE_PENDING,
    WALK_SERVICE,
}

internal enum class WalkServiceHandoff { NONE, STARTING, RESUMING }

internal data class LocationOwnershipState(
    val visibility: AppVisibility,
    val feed: LocationFeed,
    val walk: TrackingState,
    val handoff: WalkServiceHandoff = WalkServiceHandoff.NONE,
)

/**
 * Pure ownership contract for device, replay and foreground-service location subscriptions.
 *
 * It decides who may collect; it does not start a tracker or mutate UI state. Keeping those side
 * effects outside makes every state combination testable while [LocationFeedCoordinator] applies
 * the decision to the screen tracker.
 */
internal object LocationOwnershipPolicy {
    fun owner(state: LocationOwnershipState): LocationOwner = when {
        state.handoff != WalkServiceHandoff.NONE -> LocationOwner.WALK_SERVICE_PENDING
        state.walk == TrackingState.RECORDING -> LocationOwner.WALK_SERVICE
        state.visibility == AppVisibility.BACKGROUND -> LocationOwner.NONE
        state.walk == TrackingState.PAUSED && state.feed == LocationFeed.REPLAY -> LocationOwner.NONE
        state.feed == LocationFeed.DEVICE -> LocationOwner.SCREEN_DEVICE
        else -> LocationOwner.SCREEN_REPLAY
    }

    fun canStartReplay(walk: TrackingState): Boolean = walk == TrackingState.OFF

    fun canStartWalk(feed: LocationFeed): Boolean = feed == LocationFeed.DEVICE
}

internal val LocationOwner.isScreenOwner: Boolean
    get() = this == LocationOwner.SCREEN_DEVICE || this == LocationOwner.SCREEN_REPLAY
