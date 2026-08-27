package com.daengs.geo.map

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.location.LocationSample
import com.daengs.geo.location.LocationSource
import com.daengs.geo.location.LocationUpdateConfig
import com.daengs.geo.walk.TrackingState
import com.daengs.geo.walk.TrailSnapshot
import com.daengs.geo.walk.WalkTrackingState
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class LocationFeedCoordinatorTest {
    @Test
    fun `device request starts the one visible feed but mock never becomes device location`() = runTest {
        val source = FakeCoordinatorLocationSource(fix = fix(37.5665, 126.9780, isMock = true))
        val walk = MutableStateFlow(WalkTrackingState())
        val coordinator = LocationFeedCoordinator(source, walk, backgroundScope)
        coordinator.onAppForeground()

        val result = coordinator.requestDeviceFix()
        runCurrent()

        assertTrue(result.isSuccess)
        assertEquals(1, source.subscriptions)
        assertEquals(GeoPoint(37.5665, 126.9780), coordinator.state.value.feedSample?.point)
        assertNull(coordinator.state.value.deviceLocation)
    }

    @Test
    fun `walk state hands the subscription from screen to service and back when paused`() = runTest {
        val source = FakeCoordinatorLocationSource(fix = fix(37.5665, 126.9780))
        val walk = MutableStateFlow(WalkTrackingState())
        val coordinator = LocationFeedCoordinator(source, walk, backgroundScope)
        coordinator.onAppForeground()
        coordinator.requestDeviceFix()
        runCurrent()
        assertEquals(1, source.activeSubscriptions)

        val serviceFix = fix(37.5700, 126.9800)
        walk.value = WalkTrackingState(
            trail = TrailSnapshot(state = TrackingState.RECORDING),
            lastSample = serviceFix,
        )
        runCurrent()
        assertEquals(0, source.activeSubscriptions)
        assertEquals(serviceFix.point, coordinator.state.value.deviceLocation)
        assertEquals(serviceFix, coordinator.state.value.feedSample)

        walk.value = WalkTrackingState(trail = TrailSnapshot(state = TrackingState.PAUSED))
        runCurrent()
        assertEquals(1, source.activeSubscriptions)
        assertEquals(2, source.subscriptions)
    }

    @Test
    fun `start handoff blocks replay until the service acknowledges recording`() = runTest {
        val source = FakeCoordinatorLocationSource(fix = fix(37.5665, 126.9780))
        val walk = MutableStateFlow(WalkTrackingState())
        val coordinator = LocationFeedCoordinator(source, walk, backgroundScope)
        coordinator.onAppForeground()
        coordinator.requestDeviceFix()
        runCurrent()
        assertEquals(1, source.activeSubscriptions)

        assertTrue(coordinator.prepareWalkStart() is LocationCommandResult.Accepted)
        runCurrent()
        assertEquals(0, source.activeSubscriptions)
        assertEquals(
            LocationCommandResult.Rejected("동선 기록 중에는 가상 이동을 시작할 수 없어요."),
            coordinator.startReplay(10.0),
        )
        assertEquals(1, source.subscriptions)

        walk.value = WalkTrackingState(trail = TrailSnapshot(state = TrackingState.RECORDING))
        runCurrent()
        assertEquals(0, source.activeSubscriptions)
    }

    @Test
    fun `initial paused state materializes the device screen owner on foreground`() = runTest {
        val source = FakeCoordinatorLocationSource(fix = fix(37.5665, 126.9780))
        val walk = MutableStateFlow(
            WalkTrackingState(trail = TrailSnapshot(state = TrackingState.PAUSED)),
        )
        val coordinator = LocationFeedCoordinator(source, walk, backgroundScope)
        runCurrent()

        coordinator.onAppForeground()
        runCurrent()

        assertEquals(1, source.subscriptions)
        assertEquals(1, source.activeSubscriptions)
    }

    @Test
    fun `initial recording state never starts a screen subscription`() = runTest {
        val source = FakeCoordinatorLocationSource(fix = fix(37.5665, 126.9780))
        val walk = MutableStateFlow(
            WalkTrackingState(trail = TrailSnapshot(state = TrackingState.RECORDING)),
        )
        val coordinator = LocationFeedCoordinator(source, walk, backgroundScope)
        coordinator.onAppForeground()
        runCurrent()

        assertEquals(0, source.subscriptions)
        assertEquals(0, source.activeSubscriptions)
    }

    @Test
    fun `resume handoff cannot reopen the screen feed before recording acknowledgement`() = runTest {
        val source = FakeCoordinatorLocationSource(fix = fix(37.5665, 126.9780))
        val walk = MutableStateFlow(
            WalkTrackingState(trail = TrailSnapshot(state = TrackingState.PAUSED)),
        )
        val coordinator = LocationFeedCoordinator(source, walk, backgroundScope)
        coordinator.onAppForeground()
        runCurrent()
        assertEquals(1, source.activeSubscriptions)

        assertTrue(coordinator.prepareWalkResume() is LocationCommandResult.Accepted)
        coordinator.onAppBackground()
        coordinator.onAppForeground()
        coordinator.requestDeviceFix()
        runCurrent()

        assertEquals(1, source.subscriptions)
        assertEquals(0, source.activeSubscriptions)
        walk.value = WalkTrackingState(trail = TrailSnapshot(state = TrackingState.RECORDING))
        runCurrent()
        assertEquals(0, source.activeSubscriptions)
    }

    @Test
    fun `finite replay returns to device without replacing the real fix`() = runTest {
        val device = FakeCoordinatorLocationSource(fix = fix(37.5665, 126.9780))
        val replayPoint = GeoPoint(35.1796, 129.0756)
        val walk = MutableStateFlow(WalkTrackingState())
        val coordinator = LocationFeedCoordinator(
            deviceLocationSource = device,
            walkState = walk,
            scope = backgroundScope,
            replaySource = { _, _ ->
                object : LocationSource {
                    override suspend fun currentLocation() =
                        fix(replayPoint.latitude, replayPoint.longitude, true)

                    override fun locationUpdates(config: LocationUpdateConfig): Flow<LocationSample> =
                        flowOf(fix(replayPoint.latitude, replayPoint.longitude, true))
                }
            },
        )
        coordinator.onAppForeground()
        coordinator.requestDeviceFix()
        runCurrent()

        assertTrue(coordinator.startReplay(10.0) is LocationCommandResult.Accepted)
        runCurrent()

        assertEquals(LocationFeed.DEVICE, coordinator.state.value.feed)
        assertEquals(GeoPoint(37.5665, 126.9780), coordinator.state.value.deviceLocation)
    }

    @Test
    fun `replay admission reads controller state rather than a delayed screen mirror`() = runTest {
        val walk = MutableStateFlow(
            WalkTrackingState(trail = TrailSnapshot(state = TrackingState.RECORDING)),
        )
        val coordinator = LocationFeedCoordinator(
            deviceLocationSource = FakeCoordinatorLocationSource(fix = fix(37.5665, 126.9780)),
            walkState = walk,
            scope = backgroundScope,
        )

        val result = coordinator.startReplay(10.0)

        assertEquals(
            LocationCommandResult.Rejected("동선 기록 중에는 가상 이동을 시작할 수 없어요."),
            result,
        )
        assertEquals(LocationFeed.DEVICE, coordinator.state.value.feed)
    }

    private fun fix(
        latitude: Double,
        longitude: Double,
        isMock: Boolean = false,
    ) = LocationSample(
        point = GeoPoint(latitude, longitude),
        capturedAtMillis = 1L,
        accuracyMeters = 6f,
        isMock = isMock,
    )
}

private class FakeCoordinatorLocationSource(
    var fix: LocationSample,
) : LocationSource {
    private val updates = MutableSharedFlow<LocationSample>(extraBufferCapacity = 8)
    var subscriptions = 0
        private set
    var activeSubscriptions = 0
        private set

    override suspend fun currentLocation(): LocationSample = fix

    override fun locationUpdates(config: LocationUpdateConfig): Flow<LocationSample> = flow {
        subscriptions++
        activeSubscriptions++
        try {
            updates.collect(::emit)
        } finally {
            activeSubscriptions--
        }
    }
}
