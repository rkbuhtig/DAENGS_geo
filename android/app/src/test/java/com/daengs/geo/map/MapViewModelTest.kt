package com.daengs.geo.map

import com.daengs.geo.hospital.HospitalApi
import com.daengs.geo.hospital.HospitalRepository
import com.daengs.geo.location.GeoPoint
import com.daengs.geo.location.LocationSample
import com.daengs.geo.location.LocationSource
import com.daengs.geo.location.LocationUpdateConfig
import com.daengs.geo.map.layers.trail.TrackingState
import com.daengs.geo.territory.InMemoryTerritoryRepository
import com.daengs.geo.territory.LocalHexCellIndexer
import com.daengs.geo.walk.WalkFactSource
import java.io.IOException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
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
    fun `a fix that arrives after the app is backgrounded does not revive the feed`() = runTest {
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
    fun `a failing feed surfaces an error instead of taking down the scope`() = runTest {
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
    fun `replay does not clear what the user recorded and is not stitched onto it`() = runTest {
        val source = FakeLocationSource(fix = fix(37.5665, 126.9780))
        val viewModel = viewModel(source)
        viewModel.onAppForeground()
        viewModel.useDeviceLocation()
        advanceUntilIdle()
        viewModel.startTracking()
        source.updates.emit(fix(37.5670, 126.9780))
        advanceUntilIdle()
        val recorded = viewModel.uiState.value.trail.sampleCount
        assertTrue(recorded > 0)

        viewModel.startReplay(10.0)
        advanceUntilIdle()

        val trail = viewModel.uiState.value.trail
        assertEquals(TrackingState.RECORDING, trail.state)
        assertTrue(trail.sampleCount > recorded)
        assertTrue(trail.segments.size >= 2)
    }

    @Test
    fun `stopping a recording exposes local walk facts preview`() = runTest {
        val source = FakeLocationSource(fix = fix(37.5665, 126.9780))
        val viewModel = viewModel(source)
        viewModel.onAppForeground()
        viewModel.useDeviceLocation()
        advanceUntilIdle()
        viewModel.startTracking()

        source.updates.emit(fix(37.0, 127.0, isMock = true, capturedAtMillis = 1_000, elapsedMillis = 0))
        source.updates.emit(
            fix(37.000117, 127.0, isMock = true, capturedAtMillis = 11_000, elapsedMillis = 10_000),
        )
        advanceUntilIdle()
        viewModel.stopTracking()

        val preview = requireNotNull(viewModel.uiState.value.walkFactsPreview)
        assertEquals(10, preview.durationSeconds)
        assertEquals(2, preview.fixCount)
        assertEquals(WalkFactSource.MOCK, preview.source)
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

    private fun viewModel(source: LocationSource) = MapViewModel(
        hospitalRepository = HospitalRepository(HospitalApi("http://127.0.0.1:1")),
        deviceLocationSource = source,
        territoryRepository = InMemoryTerritoryRepository(LocalHexCellIndexer()),
    )

    private fun fix(
        latitude: Double,
        longitude: Double,
        isMock: Boolean = false,
        capturedAtMillis: Long = 1L,
        elapsedMillis: Long? = null,
    ) = LocationSample(
        point = GeoPoint(latitude, longitude),
        capturedAtMillis = capturedAtMillis,
        elapsedRealtimeNanos = elapsedMillis?.times(1_000_000),
        accuracyMeters = 6f,
        isMock = isMock,
    )
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
