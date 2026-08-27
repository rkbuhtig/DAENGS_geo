package com.daengs.geo.map

import com.daengs.geo.hospital.HospitalApi
import com.daengs.geo.hospital.HospitalRepository
import com.daengs.geo.hospital.HospitalSearchResponse
import com.daengs.geo.hospital.LocationMode
import com.daengs.geo.location.GeoPoint
import com.daengs.geo.location.LocationSample
import com.daengs.geo.location.LocationSource
import com.daengs.geo.location.LocationUpdateConfig
import com.daengs.geo.map.layers.trail.TrackingState
import com.daengs.geo.map.layers.trail.TrailSnapshot
import com.daengs.geo.place.PlaceKey
import com.daengs.geo.place.PlaceKind
import com.daengs.geo.place.PlaceSearchRequest
import com.daengs.geo.place.PlaceSearchResponse
import com.daengs.geo.place.PlaceSearchRepository
import com.daengs.geo.place.toPlaceSearchResponse
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
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
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
    fun `replay stays blocked when the screen mirror of the walk state lags`() = runTest {
        // 기본 @Before 는 Unconfined 라 컨트롤러 emit 이 곧바로 uiState 에 반영된다. 여기서만
        // 지연 디스패처를 써서, 화면 미러가 아직 OFF 인 창을 만든다. 소유권 판정이 uiState 를
        // 읽으면 그 창에서 산책 중에 replay 가 켜진다.
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val source = FakeLocationSource(fix = fix(37.5665, 126.9780))
        val walk = FakeWalkTrackingController()
        val viewModel = viewModel(source, walk)
        viewModel.onAppForeground()
        viewModel.useDeviceLocation()
        advanceUntilIdle()

        viewModel.startTracking()
        assertEquals(TrackingState.OFF, viewModel.uiState.value.trail.state)   // 미러는 아직 뒤처짐
        viewModel.startReplay(10.0)

        assertEquals(LocationFeed.DEVICE, viewModel.uiState.value.locationFeed)
        assertEquals("동선 기록 중에는 가상 이동을 시작할 수 없어요.", viewModel.uiState.value.statusMessage)
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

    @Test
    fun `a pending device fix times out and keeps location as the retry target`() = runTest {
        val source = FakeLocationSource(fix = fix(37.5665, 126.9780)).apply {
            gate = CompletableDeferred()
        }
        val viewModel = viewModel(source)

        viewModel.locateAndSearch()

        assertEquals(RequestKind.LOCATION, viewModel.uiState.value.request)
        advanceUntilIdle()

        val failed = viewModel.uiState.value
        assertNull(failed.request)
        assertEquals(RequestKind.LOCATION, failed.failedRequest)
        assertTrue(failed.error.orEmpty().startsWith("위치를 찾지 못했어요."))
        assertEquals(1, source.currentLocationCalls)

        viewModel.retry()

        assertEquals(2, source.currentLocationCalls)
        assertEquals(RequestKind.LOCATION, viewModel.uiState.value.request)
    }

    @Test
    fun `a location failure remains the retry target when old results exist`() {
        val state = MapUiState(
            response = HospitalSearchResponse(
                state = buildJsonObject {
                    put("lat", 37.5665)
                    put("lng", 126.9780)
                },
                results = emptyList(),
                actions = emptyList(),
                reply = "",
                showCallCta = false,
                callReasons = emptyList(),
                resolution = emptyList(),
            ),
            failedRequest = RequestKind.LOCATION,
        )

        assertEquals(RequestKind.LOCATION, retryRequestFor(state))
    }

    @Test
    fun `canonical place search uses real device origin dog and explicit preference`() = runTest {
        val source = FakeLocationSource(fix = fix(37.5665, 126.9780))
        val places = FakePlaceSearchRepository(response = placeResponse())
        val viewModel = viewModel(source, places = places, dogId = "janggun")

        viewModel.searchPlaces(
            kinds = listOf(PlaceKind.CAFE, PlaceKind.HOSPITAL),
            preferParking = true,
        )
        advanceUntilIdle()

        val request = places.requests.single()
        val state = viewModel.uiState.value
        assertEquals(GeoPoint(37.5665, 126.9780), request.origin)
        assertEquals("janggun", request.dogId)
        assertTrue(request.preferParking)
        assertEquals(listOf(PlaceKind.CAFE, PlaceKind.HOSPITAL), request.kinds)
        assertEquals(places.response, state.placeDiscovery.response)
        assertEquals(PlaceKey("kcisa", "cafe-parking"), state.placeDiscovery.selectedPlaceKey)
        assertEquals(request.origin, state.placeDiscovery.origin)
        assertNull("canonical origin must not overwrite the legacy hospital origin", state.searchOrigin)
        assertNull(state.request)
    }

    @Test
    fun `a mock current fix never becomes a canonical place search origin`() = runTest {
        val source = FakeLocationSource(fix = fix(35.1796, 129.0756, isMock = true))
        val places = FakePlaceSearchRepository(response = PlaceSearchResponse(null, emptyList()))
        val viewModel = viewModel(source, places = places)

        viewModel.searchPlaces(listOf(PlaceKind.CAFE))
        advanceUntilIdle()

        val state = viewModel.uiState.value
        assertTrue(places.requests.isEmpty())
        assertNull(state.deviceLocation)
        assertEquals(RequestKind.LOCATION, state.failedRequest)
        assertEquals("가상 위치로는 주변 장소를 검색할 수 없어요.", state.error)
    }

    @Test
    fun `camera place search pins exactly the visible center`() = runTest {
        val places = FakePlaceSearchRepository(response = PlaceSearchResponse(null, emptyList()))
        val viewModel = viewModel(
            FakeLocationSource(fix = fix(37.5665, 126.9780)),
            places = places,
        )
        val camera = GeoPoint(35.1796, 129.0756)
        viewModel.onCameraIdle(camera)

        viewModel.searchPlacesAtCamera(listOf(PlaceKind.SHOPPING))
        advanceUntilIdle()

        assertEquals(camera, places.requests.single().origin)
        assertEquals(LocationMode.PINNED, viewModel.uiState.value.locationMode)
        assertEquals(false, viewModel.uiState.value.followDevice)
    }

    @Test
    fun `failed canonical search retries the exact typed request`() = runTest {
        val source = FakeLocationSource(fix = fix(37.5665, 126.9780))
        val places = FakePlaceSearchRepository(
            response = PlaceSearchResponse(null, emptyList()),
            failure = IOException("place api unavailable"),
        )
        val viewModel = viewModel(source, places = places)
        viewModel.useDeviceLocation()
        advanceUntilIdle()

        viewModel.searchPlaces(listOf(PlaceKind.PET_SHOP), preferParking = true)
        advanceUntilIdle()

        assertEquals("place api unavailable", viewModel.uiState.value.placeDiscovery.error)
        val failedRequest = places.requests.single()

        places.failure = null
        viewModel.retryPlaceSearch()
        advanceUntilIdle()

        assertEquals(listOf(failedRequest, failedRequest), places.requests)
        assertNull(viewModel.uiState.value.placeDiscovery.error)
    }

    @Test
    fun `place location timeout keeps canonical search as the retry target`() = runTest {
        val places = FakePlaceSearchRepository(response = PlaceSearchResponse(null, emptyList()))
        val source = FakeLocationSource(fix = fix(37.5665, 126.9780)).apply {
            gate = CompletableDeferred()
        }
        val viewModel = viewModel(
            source,
            places = places,
        )

        viewModel.searchPlaces(listOf(PlaceKind.CAFE))
        advanceUntilIdle()

        assertTrue(places.requests.isEmpty())
        assertEquals(RequestKind.LOCATION, viewModel.uiState.value.failedRequest)
        assertTrue(viewModel.uiState.value.error.orEmpty().startsWith("위치를 찾지 못했어요."))

        source.gate.complete(Unit)
        viewModel.retry()
        advanceUntilIdle()

        assertEquals(PlaceKind.CAFE, places.requests.single().kinds.single())
        assertNull(viewModel.uiState.value.failedRequest)
    }

    private fun viewModel(
        source: LocationSource,
        walk: WalkTrackingController = FakeWalkTrackingController(),
        places: PlaceSearchRepository = FakePlaceSearchRepository(
            response = PlaceSearchResponse(null, emptyList()),
        ),
        dogId: String = "",
    ) = MapViewModel(
        hospitalRepository = HospitalRepository(HospitalApi(baseUrl = { "http://127.0.0.1:1" })),
        placeRepository = places,
        dogId = dogId,
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

    private fun placeResponse(): PlaceSearchResponse {
        val text = javaClass.getResource("/place_search_response.json")!!.readText()
        return Json.parseToJsonElement(text).jsonObject.toPlaceSearchResponse()
    }
}

private class FakePlaceSearchRepository(
    val response: PlaceSearchResponse,
    var failure: Throwable? = null,
) : PlaceSearchRepository {
    val requests = mutableListOf<PlaceSearchRequest>()

    override suspend fun search(request: PlaceSearchRequest): PlaceSearchResponse {
        requests += request
        failure?.let { throw it }
        return response
    }
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
    var currentLocationCalls = 0
        private set

    override suspend fun currentLocation(): LocationSample {
        currentLocationCalls++
        gate.await()
        return fix
    }

    override fun locationUpdates(config: LocationUpdateConfig): Flow<LocationSample> = flow {
        subscriptions++
        updatesFailure?.let { throw it }
        updates.collect { emit(it) }
    }
}
