package com.daengs.geo.map

import com.daengs.geo.walk.TrackingState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LocationOwnershipPolicyTest {
    @Test
    fun `every visibility feed and walk combination has one explicit owner`() {
        val cases = listOf(
            case(AppVisibility.BACKGROUND, LocationFeed.DEVICE, TrackingState.OFF, LocationOwner.NONE),
            case(AppVisibility.BACKGROUND, LocationFeed.REPLAY, TrackingState.OFF, LocationOwner.NONE),
            case(AppVisibility.BACKGROUND, LocationFeed.DEVICE, TrackingState.PAUSED, LocationOwner.NONE),
            case(AppVisibility.BACKGROUND, LocationFeed.REPLAY, TrackingState.PAUSED, LocationOwner.NONE),
            case(
                AppVisibility.BACKGROUND,
                LocationFeed.DEVICE,
                TrackingState.RECORDING,
                LocationOwner.WALK_SERVICE,
            ),
            case(
                AppVisibility.BACKGROUND,
                LocationFeed.REPLAY,
                TrackingState.RECORDING,
                LocationOwner.WALK_SERVICE,
            ),
            case(
                AppVisibility.FOREGROUND,
                LocationFeed.DEVICE,
                TrackingState.OFF,
                LocationOwner.SCREEN_DEVICE,
            ),
            case(
                AppVisibility.FOREGROUND,
                LocationFeed.REPLAY,
                TrackingState.OFF,
                LocationOwner.SCREEN_REPLAY,
            ),
            case(
                AppVisibility.FOREGROUND,
                LocationFeed.DEVICE,
                TrackingState.PAUSED,
                LocationOwner.SCREEN_DEVICE,
            ),
            case(AppVisibility.FOREGROUND, LocationFeed.REPLAY, TrackingState.PAUSED, LocationOwner.NONE),
            case(
                AppVisibility.FOREGROUND,
                LocationFeed.DEVICE,
                TrackingState.RECORDING,
                LocationOwner.WALK_SERVICE,
            ),
            case(
                AppVisibility.FOREGROUND,
                LocationFeed.REPLAY,
                TrackingState.RECORDING,
                LocationOwner.WALK_SERVICE,
            ),
        )

        cases.forEach { entry ->
            assertEquals(entry.toString(), entry.owner, LocationOwnershipPolicy.owner(entry.state))
        }
    }

    @Test
    fun `replay only starts without an active walk session`() {
        assertTrue(LocationOwnershipPolicy.canStartReplay(TrackingState.OFF))
        assertFalse(LocationOwnershipPolicy.canStartReplay(TrackingState.PAUSED))
        assertFalse(LocationOwnershipPolicy.canStartReplay(TrackingState.RECORDING))
    }

    @Test
    fun `a production walk only starts from the device feed`() {
        assertTrue(LocationOwnershipPolicy.canStartWalk(LocationFeed.DEVICE))
        assertFalse(LocationOwnershipPolicy.canStartWalk(LocationFeed.REPLAY))
    }

    private fun case(
        visibility: AppVisibility,
        feed: LocationFeed,
        walk: TrackingState,
        owner: LocationOwner,
    ) = OwnershipCase(LocationOwnershipState(visibility, feed, walk), owner)

    private data class OwnershipCase(
        val state: LocationOwnershipState,
        val owner: LocationOwner,
    )
}
