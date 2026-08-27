package com.daengs.geo.map

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.daengs.geo.hospital.HospitalRepository
import com.daengs.geo.hospital.HospitalSearchResponse
import com.daengs.geo.hospital.LocationMode
import com.daengs.geo.hospital.SearchRequestBuilder
import com.daengs.geo.hospital.SearchSession
import com.daengs.geo.hospital.SuggestedAction
import com.daengs.geo.location.FeedStatus
import com.daengs.geo.location.GeoPoint
import com.daengs.geo.location.LocationSample
import com.daengs.geo.location.LocationSource
import com.daengs.geo.location.LocationTracker
import com.daengs.geo.location.ReplayLocationSource
import com.daengs.geo.map.features.places.PlaceDiscoveryController
import com.daengs.geo.map.features.places.PlaceDiscoveryState
import com.daengs.geo.map.features.places.PlaceOriginMode
import com.daengs.geo.place.PlaceKey
import com.daengs.geo.place.PlaceKind
import com.daengs.geo.place.PlaceSearchRepository
import com.daengs.geo.territory.ClaimRejectReason
import com.daengs.geo.territory.ClaimResult
import com.daengs.geo.territory.TerritoryCell
import com.daengs.geo.territory.TerritoryRepository
import com.daengs.geo.walk.TrackingState
import com.daengs.geo.walk.TrailSnapshot
import com.daengs.geo.walk.WalkTrackingController
import com.daengs.geo.walk.WalkTrackingState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonArray

enum class LocationFeed { DEVICE, REPLAY }

enum class RequestKind { LOCATION, HOSPITAL_SEARCH }

data class MapLayerPreferences(
    val showTrail: Boolean = true,
    val showTerritory: Boolean = false,
)

private data class PlaceSearchIntent(
    val kinds: List<PlaceKind>,
    val preferParking: Boolean,
)

data class MapUiState(
    /**
     * Where the user actually is. Only a real device fix ever writes this, because it is what a
     * FOLLOW_DEVICE search sends as its origin and what the "내 위치 기준" label promises.
     */
    val deviceLocation: GeoPoint? = null,
    /**
     * What the live feed says. A debug replay may write this while no walk is being recorded;
     * production walk recording is owned separately by WalkTrackingService.
     */
    val feedSample: LocationSample? = null,
    val searchOrigin: GeoPoint? = null,
    val cameraCandidate: GeoPoint? = null,
    val followDevice: Boolean = true,
    val locationMode: LocationMode = LocationMode.FOLLOW_DEVICE,
    val locationFeed: LocationFeed = LocationFeed.DEVICE,
    val response: HospitalSearchResponse? = null,
    val selectedHospitalId: Long? = null,
    /** Canonical place discovery stays separate until the legacy hospital screen migrates. */
    val placeDiscovery: PlaceDiscoveryState = PlaceDiscoveryState(),
    val trail: TrailSnapshot = TrailSnapshot(),
    val layers: MapLayerPreferences = MapLayerPreferences(),
    val territoryCells: List<TerritoryCell> = emptyList(),
    val currentTerritoryCell: TerritoryCell? = null,
    val statusMessage: String? = null,
    val request: RequestKind? = null,
    val failedRequest: RequestKind? = null,
    val error: String? = null,
) {
    val loading: Boolean get() = request != null || placeDiscovery.loading
}

class MapViewModel(
    private val hospitalRepository: HospitalRepository,
    placeRepository: PlaceSearchRepository,
    dogId: String,
    private val deviceLocationSource: LocationSource,
    private val territoryRepository: TerritoryRepository,
    private val walkTrackingController: WalkTrackingController,
) : ViewModel() {
    private val _uiState = MutableStateFlow(MapUiState())
    val uiState: StateFlow<MapUiState> = _uiState.asStateFlow()

    /** Screen-only live feed. Walk recording itself is owned by WalkTrackingService. */
    private val locationTracker = LocationTracker(viewModelScope)

    private var appVisibility = AppVisibility.BACKGROUND
    private var activeSource: LocationSource? = null
    private var observedWalkState = TrackingState.OFF
    private var lastWalkError: String? = null
    private var pendingPlaceIntent: PlaceSearchIntent? = null
    private val placeDiscovery = PlaceDiscoveryController(
        repository = placeRepository,
        dogId = dogId,
        scope = viewModelScope,
    )

    init {
        viewModelScope.launch {
            locationTracker.updates.collect(::acceptLocation)
        }
        viewModelScope.launch {
            locationTracker.status.collect(::onFeedStatus)
        }
        viewModelScope.launch {
            walkTrackingController.state.collect(::acceptWalkTrackingState)
        }
        viewModelScope.launch {
            territoryRepository.claimedCells.collect { cells ->
                _uiState.update { it.copy(territoryCells = cells) }
            }
        }
        viewModelScope.launch {
            placeDiscovery.state.collect { discovery ->
                _uiState.update { it.copy(placeDiscovery = discovery) }
            }
        }
    }

    fun locateAndSearch() {
        pendingPlaceIntent = null
        viewModelScope.launch {
            _uiState.update {
                it.copy(request = RequestKind.LOCATION, failedRequest = null, error = null)
            }
            val sample = fetchDeviceFix() ?: return@launch
            _uiState.update {
                it.copy(
                    locationMode = LocationMode.FOLLOW_DEVICE,
                    cameraCandidate = sample.point,
                )
            }
            search()
        }
    }

    fun useDeviceLocation() {
        viewModelScope.launch {
            _uiState.update {
                it.copy(request = RequestKind.LOCATION, failedRequest = null, error = null)
            }
            if (fetchDeviceFix() == null) return@launch
            _uiState.update {
                it.copy(request = null, statusMessage = "실제 기기 위치를 사용합니다.")
            }
        }
    }

    fun startReplay(speedMultiplier: Double) {
        if (!LocationOwnershipPolicy.canStartReplay(currentWalkState())) {
            _uiState.update { it.copy(statusMessage = "동선 기록 중에는 가상 이동을 시작할 수 없어요.") }
            return
        }
        val state = _uiState.value
        val origin = state.feedSample?.point ?: state.deviceLocation ?: DEFAULT_REPLAY_ORIGIN
        val source = ReplayLocationSource(
            points = ReplayLocationSource.loopAround(origin),
            speedMultiplier = speedMultiplier,
        )
        // Replay is a UI/debug fixture. It never becomes the owner of a production walk session.
        switchFeed(
            feed = LocationFeed.REPLAY,
            source = source,
            statusMessage = "가상 이동 ${speedMultiplier.toInt()}배속 재생 중",
        )
    }

    fun onCameraIdle(point: GeoPoint) {
        _uiState.update { it.copy(cameraCandidate = point) }
    }

    fun onCameraGesture() {
        _uiState.update { it.copy(followDevice = false) }
    }

    fun onAppForeground() {
        if (appVisibility == AppVisibility.FOREGROUND) return
        appVisibility = AppVisibility.FOREGROUND
        val source = activeSource ?: return
        if (currentLocationOwner().isScreenOwner) locationTracker.start(source)
    }

    fun onAppBackground() {
        appVisibility = AppVisibility.BACKGROUND
        // This stops only the screen-owned feed. A running WalkTrackingService keeps its own
        // location subscription and recording state alive after the Activity leaves the screen.
        locationTracker.stop()
        endReplay("화면을 벗어나 가상 이동을 종료했어요.")
    }

    fun searchPinnedArea() {
        val state = _uiState.value
        val point = state.cameraCandidate ?: return
        if (state.response == null) return
        _uiState.update { it.copy(locationMode = LocationMode.PINNED, followDevice = false) }
        search(SearchRequestBuilder.setOriginEdit(point))
    }

    fun followMyLocation() = locateAndSearch()

    fun execute(action: SuggestedAction) = search(action.edits)

    fun searchAtHundredMeters() = search(SearchRequestBuilder.setRadiusEdit(100))

    fun retry() {
        when (retryRequestFor(_uiState.value)) {
            RequestKind.LOCATION -> pendingPlaceIntent?.let { intent ->
                searchPlaces(intent.kinds, intent.preferParking)
            } ?: locateAndSearch()
            RequestKind.HOSPITAL_SEARCH -> search()
        }
    }

    fun retryPlaceSearch() = placeDiscovery.retry()

    fun selectHospital(id: Long) {
        _uiState.update { it.copy(selectedHospitalId = id) }
    }

    /** Search canonical Place kinds around the last real device fix. */
    fun searchPlaces(
        kinds: List<PlaceKind>,
        preferParking: Boolean = false,
    ) {
        val intent = PlaceSearchIntent(kinds, preferParking)
        val origin = _uiState.value.deviceLocation
        if (origin != null) {
            beginPlaceDiscovery(origin, intent)
            return
        }

        locateForPlaceDiscovery(intent)
    }

    /** Refresh the real fix even when an older device location is already available. */
    fun locateAndSearchPlaces(
        kinds: List<PlaceKind>,
        preferParking: Boolean = false,
    ) {
        locateForPlaceDiscovery(PlaceSearchIntent(kinds, preferParking))
    }

    private fun locateForPlaceDiscovery(intent: PlaceSearchIntent) {
        pendingPlaceIntent = intent
        viewModelScope.launch {
            _uiState.update {
                it.copy(request = RequestKind.LOCATION, failedRequest = null, error = null)
            }
            val realOrigin = fetchRealDevicePoint()
            if (realOrigin == null || pendingPlaceIntent != intent) return@launch
            beginPlaceDiscovery(realOrigin, intent)
        }
    }

    /**
     * Change only the kind or the parking toggle. The area the user is looking at is a choice
     * they already made; re-deriving the origin from the device would silently undo it.
     */
    fun searchPlacesAtCurrentOrigin(
        kinds: List<PlaceKind>,
        preferParking: Boolean = false,
    ) {
        val discovery = _uiState.value.placeDiscovery
        val pinned = discovery.origin?.takeIf { discovery.originMode == PlaceOriginMode.PINNED }
        if (pinned == null) {
            searchPlaces(kinds, preferParking)
            return
        }
        beginPlaceDiscovery(pinned, PlaceSearchIntent(kinds, preferParking), PlaceOriginMode.PINNED)
    }

    /** Search the camera center explicitly; panning alone never changes the search origin. */
    fun searchPlacesAtCamera(
        kinds: List<PlaceKind>,
        preferParking: Boolean = false,
    ) {
        val origin = _uiState.value.cameraCandidate
        if (origin == null) {
            _uiState.update { it.copy(statusMessage = "지도를 이동한 뒤 이 지역을 검색해주세요.") }
            return
        }
        _uiState.update {
            it.copy(locationMode = LocationMode.PINNED, followDevice = false)
        }
        beginPlaceDiscovery(origin, PlaceSearchIntent(kinds, preferParking), PlaceOriginMode.PINNED)
    }

    fun selectPlace(key: PlaceKey) {
        placeDiscovery.select(key)
    }

    fun startTracking() {
        if (!LocationOwnershipPolicy.canStartWalk(_uiState.value.locationFeed)) {
            _uiState.update { it.copy(statusMessage = "실제 위치로 돌아온 뒤 동선 기록을 시작해주세요.") }
            return
        }
        // There must be one high-accuracy continuous subscription. The service takes ownership
        // before the Activity is allowed to disappear.
        locationTracker.stop()
        walkTrackingController.start()
    }

    fun pauseTracking() {
        walkTrackingController.pause()
    }

    fun resumeTracking() {
        locationTracker.stop()
        walkTrackingController.resume()
    }

    fun stopTracking() {
        walkTrackingController.stop()
    }

    fun toggleTrail() {
        _uiState.update { state ->
            state.copy(layers = state.layers.copy(showTrail = !state.layers.showTrail))
        }
    }

    fun toggleTerritory() {
        _uiState.update { state ->
            val enabled = !state.layers.showTerritory
            state.copy(
                layers = state.layers.copy(showTerritory = enabled),
                currentTerritoryCell = if (enabled) {
                    state.feedSample?.let { territoryRepository.cellAt(it.point) }
                } else {
                    null
                },
                statusMessage = null,
            )
        }
    }

    fun claimCurrentCell() {
        val sample = _uiState.value.feedSample
        if (sample == null) {
            _uiState.update { it.copy(statusMessage = "현재 위치를 확인한 뒤 다시 시도해주세요.") }
            return
        }
        viewModelScope.launch {
            val message = when (val result = territoryRepository.claim(sample)) {
                is ClaimResult.Claimed -> "이 영역을 내 지도에 표시했어요."
                is ClaimResult.AlreadyClaimed -> "이미 표시한 영역이에요."
                is ClaimResult.Rejected -> when (result.reason) {
                    ClaimRejectReason.MOCK_LOCATION -> "가상 이동 중에는 영역을 마킹할 수 없어요."
                    ClaimRejectReason.LOW_ACCURACY -> "위치 정확도가 낮아 마킹하지 않았어요."
                }
            }
            _uiState.update { it.copy(statusMessage = message) }
        }
    }

    /**
     * 단발 위치 하나. **반드시 유한한 시간 안에 끝난다.**
     *
     * `getCurrentLocation` 은 실내나 위치 서비스가 꺼진 상태에서 콜백을 영영 안 주기도 한다.
     * 그러면 `loading` 이 켜진 채로 남아 화면은 계속 도는데 사용자는 버튼이 먹은 건지
     * 앱이 멈춘 건지 구분할 방법이 없다. 기다림에는 끝이 있어야 하고, 끝났으면 왜 실패했는지
     * 말해야 한다.
     */
    private suspend fun fetchDeviceFix(): LocationSample? =
        runCatching {
            withTimeoutOrNull(LOCATION_TIMEOUT_MS) { deviceLocationSource.currentLocation() }
                ?: throw IllegalStateException(
                    "위치를 찾지 못했어요. 실내에서는 오래 걸릴 수 있어요 - " +
                        "창가로 나가거나 위치 설정을 확인한 뒤 다시 눌러주세요.",
                )
        }
            .onSuccess { sample ->
                switchFeed(LocationFeed.DEVICE, deviceLocationSource, statusMessage = null)
                acceptLocation(sample)
            }
            .onFailure { error -> showError(error, RequestKind.LOCATION) }
            .getOrNull()

    /** Canonical searches may use only the state slot that already rejects replay/mock fixes. */
    private suspend fun fetchRealDevicePoint(): GeoPoint? {
        if (fetchDeviceFix() == null) return null
        return _uiState.value.deviceLocation ?: run {
            showError(
                IllegalStateException("가상 위치로는 주변 장소를 검색할 수 없어요."),
                RequestKind.LOCATION,
            )
            null
        }
    }

    /** The only place the screen-owned feed starts. Walk recording has a different owner. */
    private fun switchFeed(
        feed: LocationFeed,
        source: LocationSource,
        statusMessage: String?,
    ) {
        locationTracker.stop()
        activeSource = source
        _uiState.update {
            it.copy(
                locationFeed = feed,
                feedSample = null,
                followDevice = true,
                statusMessage = statusMessage,
            )
        }
        if (currentLocationOwner().isScreenOwner) {
            locationTracker.start(source)
        }
    }

    private fun endReplay(message: String) {
        if (_uiState.value.locationFeed != LocationFeed.REPLAY) return
        switchFeed(LocationFeed.DEVICE, deviceLocationSource, statusMessage = message)
    }

    private fun onFeedStatus(status: FeedStatus) {
        when (status) {
            is FeedStatus.Failed -> {
                endReplay("가상 이동을 이어가지 못했어요.")
                showError(status.cause)
            }
            FeedStatus.Completed -> endReplay("가상 이동 재생을 마쳤어요.")
            FeedStatus.Running, FeedStatus.Idle -> Unit
        }
    }

    private fun acceptLocation(sample: LocationSample) {
        _uiState.update { state ->
            state.copy(
                feedSample = sample,
                deviceLocation = if (sample.isMock) state.deviceLocation else sample.point,
                currentTerritoryCell = if (state.layers.showTerritory) {
                    territoryRepository.cellAt(sample.point)
                } else {
                    null
                },
            )
        }
    }

    private fun acceptWalkTrackingState(walk: WalkTrackingState) {
        val previousWalkState = observedWalkState
        val previousWalkError = lastWalkError
        observedWalkState = walk.trail.state
        lastWalkError = walk.errorMessage

        _uiState.update { state ->
            val sample = walk.lastSample
            val statusMessage = when {
                walk.errorMessage != null -> walk.errorMessage
                previousWalkError != null && state.statusMessage == previousWalkError -> null
                else -> state.statusMessage
            }
            state.copy(
                trail = walk.trail,
                feedSample = if (state.locationFeed == LocationFeed.DEVICE && sample != null) {
                    sample
                } else {
                    state.feedSample
                },
                deviceLocation = if (
                    state.locationFeed == LocationFeed.DEVICE &&
                    sample != null &&
                    !sample.isMock
                ) {
                    sample.point
                } else {
                    state.deviceLocation
                },
                currentTerritoryCell = if (
                    state.layers.showTerritory &&
                    state.locationFeed == LocationFeed.DEVICE &&
                    sample != null
                ) {
                    territoryRepository.cellAt(sample.point)
                } else {
                    state.currentTerritoryCell
                },
                statusMessage = statusMessage,
            )
        }

        if (previousWalkState == walk.trail.state) return
        when (currentLocationOwner(walk.trail.state)) {
            LocationOwner.WALK_SERVICE, LocationOwner.NONE -> locationTracker.stop()
            LocationOwner.SCREEN_DEVICE -> {
                val source = activeSource ?: deviceLocationSource.also { activeSource = it }
                locationTracker.start(source)
            }
            // REPLAY 소유자에게 device source 를 쥐어주지 않는다. feed 가 REPLAY 라는 것은
            // switchFeed 가 replay source 를 넣었다는 뜻이라 activeSource 는 이미 그것이다.
            LocationOwner.SCREEN_REPLAY -> activeSource?.let(locationTracker::start)
        }
    }

    /**
     * The controller, never `uiState.trail`. The screen state is a mirror filled by the collector,
     * so between `walkTrackingController.start()` and the next emission it still reads OFF — and an
     * ownership decision taken in that window starts a second subscription.
     */
    private fun currentWalkState(): TrackingState = walkTrackingController.state.value.trail.state

    private fun currentLocationOwner(
        walk: TrackingState = currentWalkState(),
    ): LocationOwner = LocationOwnershipPolicy.owner(
        LocationOwnershipState(
            visibility = appVisibility,
            feed = _uiState.value.locationFeed,
            walk = walk,
        ),
    )

    private fun search(edits: JsonArray = JsonArray(emptyList())) {
        val before = _uiState.value
        val session = SearchSession(
            state = before.response?.state,
            deviceLocation = before.deviceLocation,
            mode = before.locationMode,
        )
        viewModelScope.launch {
            _uiState.update {
                it.copy(request = RequestKind.HOSPITAL_SEARCH, failedRequest = null, error = null)
            }
            runCatching {
                hospitalRepository.search(SearchRequestBuilder.build(session, edits))
            }.onSuccess { response ->
                _uiState.update {
                    it.copy(
                        response = response,
                        searchOrigin = response.origin,
                        selectedHospitalId = response.results.firstOrNull()?.id,
                        request = null,
                        failedRequest = null,
                        error = null,
                    )
                }
            }.onFailure { error -> showError(error, RequestKind.HOSPITAL_SEARCH) }
        }
    }

    private fun beginPlaceDiscovery(
        origin: GeoPoint,
        intent: PlaceSearchIntent,
        originMode: PlaceOriginMode = PlaceOriginMode.DEVICE,
    ) {
        pendingPlaceIntent = null
        _uiState.update {
            it.copy(request = null, failedRequest = null, error = null)
        }
        placeDiscovery.search(origin, intent.kinds, intent.preferParking, originMode)
    }

    private fun showError(error: Throwable, failedRequest: RequestKind? = null) {
        _uiState.update {
            it.copy(
                request = null,
                failedRequest = failedRequest,
                error = error.message ?: "요청을 처리하지 못했습니다.",
            )
        }
    }

    class Factory(
        private val hospitalRepository: HospitalRepository,
        private val placeRepository: PlaceSearchRepository,
        private val dogId: String,
        private val locationSource: LocationSource,
        private val territoryRepository: TerritoryRepository,
        private val walkTrackingController: WalkTrackingController,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            MapViewModel(
                hospitalRepository,
                placeRepository,
                dogId,
                locationSource,
                territoryRepository,
                walkTrackingController,
            ) as T
    }

    companion object {
        private val DEFAULT_REPLAY_ORIGIN = GeoPoint(latitude = 37.5665, longitude = 126.9780)

        /** 실측으로 잰 값이 아니라 "사람이 버튼을 다시 누르기 전에 답이 와야 한다" 는 상한이다. */
        private const val LOCATION_TIMEOUT_MS = 15_000L
    }
}

internal fun retryRequestFor(state: MapUiState): RequestKind =
    state.failedRequest
        ?: if (state.response == null) RequestKind.LOCATION else RequestKind.HOSPITAL_SEARCH
