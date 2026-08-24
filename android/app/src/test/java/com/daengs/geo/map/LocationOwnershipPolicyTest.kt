package com.daengs.geo.map

import com.daengs.geo.walk.TrackingState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LocationOwnershipPolicyTest {
    /**
     * Four of the twelve cannot be reached today: the entry rules below keep replay and an active
     * walk apart, and `onAppBackground()` ends a running replay. They are pinned anyway so that
     * relaxing an entry rule shows up here as a decision rather than as behaviour that drifts.
     */
    @Test
    fun `every visibility feed and walk combination has one explicit owner`() {
        val cases = listOf(
            case(AppVisibility.BACKGROUND, LocationFeed.DEVICE, TrackingState.OFF, LocationOwner.NONE),
            // 도달 불가 — background 진입이 replay 를 끝낸다.
            case(AppVisibility.BACKGROUND, LocationFeed.REPLAY, TrackingState.OFF, LocationOwner.NONE),
            case(AppVisibility.BACKGROUND, LocationFeed.DEVICE, TrackingState.PAUSED, LocationOwner.NONE),
            // 도달 불가 — 위와 같은 이유. 산책 중에는 replay 로 바꿀 수도 없다.
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
            // 도달 불가 — replay 는 walk OFF 에서만 시작하고, 산책은 device feed 에서만 시작한다.
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
