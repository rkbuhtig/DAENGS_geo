package com.daengs.geo.map

import com.daengs.geo.hospital.HospitalApi
import com.daengs.geo.hospital.HospitalRepository
import com.daengs.geo.location.GeoPoint
import com.daengs.geo.location.LocationSample
import com.daengs.geo.location.LocationSource
import com.daengs.geo.location.LocationUpdateConfig
import com.daengs.geo.map.layers.trail.TrackingState
import com.daengs.geo.map.layers.trail.TrailSnapshot
import com.daengs.geo.territory.InMemoryTerritoryRepository
import com.daengs.geo.territory.LocalHexCellIndexer
import com.daengs.geo.walk.WalkTrackingController
import com.daengs.geo.walk.WalkTrackingState
import java.io.IOException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class MapViewModelTest {
    @Before
    fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `a mock fix moves the map but never becomes the searchable device location`() = runTest {
        val source = FakeLocationSource(fix = fix(37.5665, 126.9780))
        val viewModel = viewModel(source)
        viewModel.onAppForeground()
        viewModel.useDeviceLocation()
        advanceUntilIdle()

        source.updates.emit(fix(35.1796, 129.0756, isMock = true))
        advanceUntilIdle()

        val state = viewModel.uiState.value
        assertEquals(GeoPoint(37.5665, 126.9780), state.deviceLocation)
        assertEquals(GeoPoint(35.1796, 129.0756), state.feedSample?.point)
    }

    @Test
    fun `a fix that arrives after the app is backgrounded does not revive the screen feed`() = runTest {
        val source = FakeLocationSource(fix = fix(37.5665, 126.9780))
        source.gate = CompletableDeferred()
        val viewModel = viewModel(source)
        viewModel.onAppForeground()

        viewModel.useDeviceLocation()
        viewModel.onAppBackground()
        source.gate.complete(Unit)
        advanceUntilIdle()

        assertEquals(0, source.subscriptions)
    }

    @Test
    fun `a fix while the app is on screen starts exactly one subscription`() = runTest {
        val source = FakeLocationSource(fix = fix(37.5665, 126.9780))
        val viewModel = viewModel(source)
        viewModel.onAppForeground()

        viewModel.useDeviceLocation()
        advanceUntilIdle()

        assertEquals(1, source.subscriptions)
        assertNotNull(viewModel.uiState.value.feedSample)
    }

    @Test
    fun `a duplicate foreground event does not restart the current subscription`() = runTest {
        val source = FakeLocationSource(fix = fix(37.5665, 126.9780))
        val viewModel = viewModel(source)
        viewModel.onAppForeground()
        viewModel.useDeviceLocation()
        advanceUntilIdle()

        viewModel.onAppForeground()
        advanceUntilIdle()

        assertEquals(1, source.subscriptions)
    }

    @Test
    fun `a failing screen feed surfaces an error instead of taking down the scope`() = runTest {
        val source = FakeLocationSource(
            fix = fix(37.5665, 126.9780),
            updatesFailure = IOException("play services unavailable"),
        )
        val viewModel = viewModel(source)
        viewModel.onAppForeground()

        viewModel.useDeviceLocation()
        advanceUntilIdle()

        assertEquals("play services unavailable", viewModel.uiState.value.error)
    }

    @Test
    fun `a finished replay hands the feed back to the device`() = runTest {
        val source = FakeLocationSource(fix = fix(37.5665, 126.9780))
        val viewModel = viewModel(source)
        viewModel.onAppForeground()
        viewModel.useDeviceLocation()
        advanceUntilIdle()

        viewModel.startReplay(10.0)
        advanceUntilIdle()

        val state = viewModel.uiState.value
        assertEquals(LocationFeed.DEVICE, state.locationFeed)
        assertEquals(GeoPoint(37.5665, 126.9780), state.deviceLocation)
        assertTrue(source.subscriptions >= 2)
    }

    @Test
    fun `walk recording belongs to the controller and app background does not stop it`() = runTest {
        val source = FakeLocationSource(fix = fix(37.5665, 126.9780))
        val walk = FakeWalkTrackingController()
        val viewModel = viewModel(source, walk)
        viewModel.onAppForeground()
        viewModel.useDeviceLocation()
        advanceUntilIdle()

        viewModel.startTracking()
        advanceUntilIdle()
        viewModel.onAppBackground()
        viewModel.startReplay(10.0)
        advanceUntilIdle()

        assertEquals(1, walk.startCalls)
        assertEquals(0, walk.stopCalls)
        assertEquals(TrackingState.RECORDING, viewModel.uiState.value.trail.state)
        assertEquals(LocationFeed.DEVICE, viewModel.uiState.value.locationFeed)
        assertEquals("동선 기록 중에는 가상 이동을 시작할 수 없어요.", viewModel.uiState.value.statusMessage)
    }

    @Test
    fun `pausing a visible walk returns the device feed to the screen`() = runTest {
        val source = FakeLocationSource(fix = fix(37.5665, 126.9780))
        val walk = FakeWalkTrackingController()
        val viewModel = viewModel(source, walk)
        viewModel.onAppForeground()
        viewModel.useDeviceLocation()
        advanceUntilIdle()

        viewModel.startTracking()
        viewModel.pauseTracking()
        advanceUntilIdle()

        assertEquals(2, source.subscriptions)
        assertEquals(TrackingState.PAUSED, viewModel.uiState.value.trail.state)
    }

    @Test
    fun `pausing a background walk does not start a screen feed`() = runTest {
        val source = FakeLocationSource(fix = fix(37.5665, 126.9780))
        val walk = FakeWalkTrackingController()
        val viewModel = viewModel(source, walk)
        viewModel.onAppForeground()
        viewModel.useDeviceLocation()
        advanceUntilIdle()

        viewModel.startTracking()
        viewModel.onAppBackground()
        viewModel.pauseTracking()
        advanceUntilIdle()

        assertEquals(1, source.subscriptions)
        assertEquals(TrackingState.PAUSED, viewModel.uiState.value.trail.state)
    }

    @Test
    fun `a production walk cannot start while replay owns the screen feed`() = runTest {
        val source = FakeLocationSource(fix = fix(37.5665, 126.9780))
        val walk = FakeWalkTrackingController()
        val viewModel = viewModel(source, walk)
        viewModel.onAppForeground()

        viewModel.startReplay(10.0)
        viewModel.startTracking()

        assertEquals(0, walk.startCalls)
        assertEquals(LocationFeed.REPLAY, viewModel.uiState.value.locationFeed)
        assertEquals("실제 위치로 돌아온 뒤 동선 기록을 시작해주세요.", viewModel.uiState.value.statusMessage)
    }

    @Test
    fun `territory preview is only computed while the layer is on`() = runTest {
        val source = FakeLocationSource(fix = fix(37.5665, 126.9780))
        val viewModel = viewModel(source)
        viewModel.onAppForeground()
        viewModel.useDeviceLocation()
        advanceUntilIdle()
        assertNull(viewModel.uiState.value.currentTerritoryCell)

        viewModel.toggleTerritory()

        assertNotNull(viewModel.uiState.value.currentTerritoryCell)
    }

    @Test
    fun `claiming without a fix explains itself instead of failing silently`() = runTest {
        val viewModel = viewModel(FakeLocationSource(fix = fix(37.5665, 126.9780)))

        viewModel.claimCurrentCell()
        advanceUntilIdle()

        assertEquals("현재 위치를 확인한 뒤 다시 시도해주세요.", viewModel.uiState.value.statusMessage)
    }

    private fun viewModel(
        source: LocationSource,
        walk: WalkTrackingController = FakeWalkTrackingController(),
    ) = MapViewModel(
        hospitalRepository = HospitalRepository(HospitalApi("http://127.0.0.1:1")),
        deviceLocationSource = source,
        territoryRepository = InMemoryTerritoryRepository(LocalHexCellIndexer()),
        walkTrackingController = walk,
    )

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

private class FakeWalkTrackingController : WalkTrackingController {
    private val mutableState = MutableStateFlow(WalkTrackingState())
    override val state: StateFlow<WalkTrackingState> = mutableState.asStateFlow()

    var startCalls = 0
        private set
    var stopCalls = 0
        private set

    override fun start() {
        startCalls++
        mutableState.value = WalkTrackingState(
            trail = TrailSnapshot(state = TrackingState.RECORDING),
        )
    }

    override fun pause() {
        mutableState.value = mutableState.value.copy(
            trail = mutableState.value.trail.copy(state = TrackingState.PAUSED),
        )
    }

    override fun resume() {
        mutableState.value = mutableState.value.copy(
            trail = mutableState.value.trail.copy(state = TrackingState.RECORDING),
        )
    }

    override fun stop() {
        stopCalls++
        mutableState.value = mutableState.value.copy(
            trail = mutableState.value.trail.copy(state = TrackingState.OFF),
        )
    }
}

private class FakeLocationSource(
    private val fix: LocationSample,
    private val updatesFailure: Throwable? = null,
) : LocationSource {
    val updates = MutableSharedFlow<LocationSample>(extraBufferCapacity = 8)
    var gate = CompletableDeferred<Unit>().apply { complete(Unit) }
    var subscriptions = 0
        private set

    override suspend fun currentLocation(): LocationSample {
        gate.await()
        return fix
    }

    override fun locationUpdates(config: LocationUpdateConfig): Flow<LocationSample> = flow {
        subscriptions++
        updatesFailure?.let { throw it }
        updates.collect { emit(it) }
    }
}
