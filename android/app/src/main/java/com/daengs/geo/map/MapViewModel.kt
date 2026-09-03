package com.daengs.geo.map

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.daengs.geo.journey.JourneyRepository
import com.daengs.geo.location.GeoPoint
import com.daengs.geo.location.LocationSample
import com.daengs.geo.location.LocationSource
import com.daengs.geo.map.features.journey.PlaceJourneyController
import com.daengs.geo.map.features.journey.PlaceJourneyState
import com.daengs.geo.map.features.places.PlaceDiscoveryController
import com.daengs.geo.map.features.places.PlaceDiscoveryState
import com.daengs.geo.map.features.places.PlaceOriginMode
import com.daengs.geo.map.shell.MapPurpose
import com.daengs.geo.place.DogSearchContext
import com.daengs.geo.place.PlaceKey
import com.daengs.geo.place.PlaceKind
import com.daengs.geo.place.PlaceResult
import com.daengs.geo.place.PlaceSearchRepository
import com.daengs.geo.territory.ClaimRejectReason
import com.daengs.geo.territory.ClaimResult
import com.daengs.geo.territory.TerritoryCell
import com.daengs.geo.territory.TerritoryRepository
import com.daengs.geo.walk.TrailSnapshot
import com.daengs.geo.walk.WalkTrackingController
import com.daengs.geo.walk.WalkTrackingState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class MapLayerPreferences(
    val showTrail: Boolean = true,
)

private data class PlaceSearchIntent(
    val kinds: List<PlaceKind>,
    val preferParking: Boolean,
)

data class MapUiState(
    /**
     * Where the user actually is. Only a real device fix ever writes this, because it is what a
     * A device-origin Place search sends this point and the "내 위치 기준" label promises it.
     */
    val deviceLocation: GeoPoint? = null,
    /**
     * What the live feed says. A debug replay may write this while no walk is being recorded;
     * production walk recording is owned separately by WalkTrackingService.
     */
    val feedSample: LocationSample? = null,
    val cameraCandidate: GeoPoint? = null,
    val followDevice: Boolean = true,
    val locationFeed: LocationFeed = LocationFeed.DEVICE,
    val placeDiscovery: PlaceDiscoveryState = PlaceDiscoveryState(),
    val journey: PlaceJourneyState = PlaceJourneyState(),
    val trail: TrailSnapshot = TrailSnapshot(),
    val layers: MapLayerPreferences = MapLayerPreferences(),
    val mapPurpose: MapPurpose = MapPurpose.PLACE_SEARCH,
    val territoryCells: List<TerritoryCell> = emptyList(),
    val currentTerritoryCell: TerritoryCell? = null,
    val statusMessage: String? = null,
    val locating: Boolean = false,
    val error: String? = null,
) {
    val loading: Boolean get() = locating || placeDiscovery.loading
}

class MapViewModel(
    placeRepository: PlaceSearchRepository,
    journeyRepository: JourneyRepository,
    // journey 는 아직 dog_id 로 외부 프로필 계약을 조회한다(결정 #58). place 검색은
    // identity 를 받지 않으므로(결정 #73) 값 묶음을 따로 받는다.
    dogId: String,
    dogContext: DogSearchContext?,
    deviceLocationSource: LocationSource,
    private val territoryRepository: TerritoryRepository,
    private val walkTrackingController: WalkTrackingController,
) : ViewModel() {
    private val _uiState = MutableStateFlow(MapUiState())
    val uiState: StateFlow<MapUiState> = _uiState.asStateFlow()

    private var lastWalkError: String? = null
    private var pendingPlaceIntent: PlaceSearchIntent? = null
    private val locationFeed = LocationFeedCoordinator(
        deviceLocationSource = deviceLocationSource,
        walkState = walkTrackingController.state,
        scope = viewModelScope,
    )
    private val placeDiscovery = PlaceDiscoveryController(
        repository = placeRepository,
        dogContext = dogContext,
        scope = viewModelScope,
    )
    private val placeJourney = PlaceJourneyController(
        repository = journeyRepository,
        dogId = dogId,
        scope = viewModelScope,
    )

    init {
        viewModelScope.launch {
            locationFeed.state.collect(::acceptLocationFeedState)
        }
        viewModelScope.launch {
            locationFeed.events.collect(::acceptLocationFeedEvent)
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
        viewModelScope.launch {
            placeJourney.state.collect { journey ->
                _uiState.update { it.copy(journey = journey) }
            }
        }
    }

    fun useDeviceLocation() {
        pendingPlaceIntent = null
        viewModelScope.launch {
            _uiState.update {
                it.copy(locating = true, error = null)
            }
            if (fetchDeviceFix() == null) return@launch
            _uiState.update {
                it.copy(locating = false, statusMessage = "실제 기기 위치를 사용합니다.")
            }
        }
    }

    fun startReplay(speedMultiplier: Double) {
        when (val result = locationFeed.startReplay(speedMultiplier)) {
            is LocationCommandResult.Accepted -> {
                acceptLocationFeedState(locationFeed.state.value)
                _uiState.update { it.copy(followDevice = true, statusMessage = result.message) }
            }
            is LocationCommandResult.Rejected -> {
                _uiState.update { it.copy(statusMessage = result.message) }
            }
        }
    }

    fun onCameraIdle(point: GeoPoint) {
        _uiState.update { it.copy(cameraCandidate = point) }
    }

    fun onCameraGesture() {
        _uiState.update { it.copy(followDevice = false) }
    }

    fun onAppForeground() {
        locationFeed.onAppForeground()
    }

    fun onAppBackground() {
        locationFeed.onAppBackground()?.let { message ->
            acceptLocationFeedState(locationFeed.state.value)
            _uiState.update { it.copy(followDevice = true, statusMessage = message) }
        }
    }

    fun retry() {
        pendingPlaceIntent?.let { intent ->
            locateForPlaceDiscovery(intent)
        } ?: useDeviceLocation()
    }

    fun retryPlaceSearch() = placeDiscovery.retry()

    fun showPlaceSearchMap() {
        _uiState.update {
            it.copy(mapPurpose = MapPurpose.PLACE_SEARCH, currentTerritoryCell = null)
        }
    }

    fun showWalkMap() {
        _uiState.update {
            it.copy(mapPurpose = MapPurpose.WALK, currentTerritoryCell = null)
        }
    }

    /** A first-class entry point that still uses the one canonical Place discovery session. */
    fun openHospitalPlaces() {
        searchPlacesAtCurrentOrigin(listOf(PlaceKind.HOSPITAL))
    }

    /** Search canonical Place kinds around the last real device fix. */
    fun searchPlaces(
        kinds: List<PlaceKind>,
        preferParking: Boolean = false,
    ) {
        showPlaceSearchMap()
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
        showPlaceSearchMap()
        locateForPlaceDiscovery(PlaceSearchIntent(kinds, preferParking))
    }

    private fun locateForPlaceDiscovery(intent: PlaceSearchIntent) {
        pendingPlaceIntent = intent
        viewModelScope.launch {
            _uiState.update {
                it.copy(locating = true, error = null)
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
        showPlaceSearchMap()
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
        showPlaceSearchMap()
        val origin = _uiState.value.cameraCandidate
        if (origin == null) {
            _uiState.update { it.copy(statusMessage = "지도를 이동한 뒤 이 지역을 검색해주세요.") }
            return
        }
        _uiState.update { it.copy(followDevice = false) }
        beginPlaceDiscovery(origin, PlaceSearchIntent(kinds, preferParking), PlaceOriginMode.PINNED)
    }

    fun selectPlace(key: PlaceKey) {
        placeDiscovery.select(key)
    }

    /** Journey always starts at the latest real device fix, never at a panned search origin. */
    fun openJourney(place: PlaceResult) {
        val origin = _uiState.value.deviceLocation
        if (origin == null) {
            placeJourney.reject(place.key, "현재 위치를 확인한 뒤 길찾기를 다시 눌러주세요.")
            return
        }
        placeJourney.load(origin, place)
    }

    fun retryJourney() = placeJourney.retry()

    fun startTracking() {
        when (val result = locationFeed.prepareWalkStart()) {
            is LocationCommandResult.Rejected -> {
                _uiState.update { it.copy(statusMessage = result.message) }
                return
            }
            is LocationCommandResult.Accepted -> {
                runCatching(walkTrackingController::start).onFailure { error ->
                    locationFeed.cancelWalkHandoff()
                    showError(error)
                }
            }
        }
    }

    fun pauseTracking() {
        walkTrackingController.pause()
    }

    fun resumeTracking() {
        when (val result = locationFeed.prepareWalkResume()) {
            is LocationCommandResult.Rejected -> {
                _uiState.update { it.copy(statusMessage = result.message) }
            }
            is LocationCommandResult.Accepted -> {
                runCatching(walkTrackingController::resume).onFailure { error ->
                    locationFeed.cancelWalkHandoff()
                    showError(error)
                }
            }
        }
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
            val entering = state.mapPurpose != MapPurpose.TERRITORY
            state.copy(
                mapPurpose = if (entering) MapPurpose.TERRITORY else MapPurpose.WALK,
                currentTerritoryCell = if (entering) {
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
    private suspend fun fetchDeviceFix(): LocationSample? = locationFeed.requestDeviceFix()
        .onSuccess {
            acceptLocationFeedState(locationFeed.state.value)
            _uiState.update { state -> state.copy(followDevice = true, statusMessage = null) }
        }
        .onFailure(::showError)
        .getOrNull()

    /** Canonical searches may use only the state slot that already rejects replay/mock fixes. */
    private suspend fun fetchRealDevicePoint(): GeoPoint? {
        if (fetchDeviceFix() == null) return null
        return _uiState.value.deviceLocation ?: run {
            showError(
                IllegalStateException("가상 위치로는 주변 장소를 검색할 수 없어요."),
            )
            null
        }
    }

    private fun acceptLocationFeedState(location: LocationFeedState) {
        _uiState.update { state ->
            state.copy(
                feedSample = location.feedSample,
                deviceLocation = location.deviceLocation,
                locationFeed = location.feed,
                currentTerritoryCell = if (
                    state.mapPurpose == MapPurpose.TERRITORY &&
                    location.feedSample != null
                ) {
                    territoryRepository.cellAt(location.feedSample.point)
                } else {
                    state.currentTerritoryCell
                },
            )
        }
    }

    private fun acceptLocationFeedEvent(event: LocationFeedEvent) {
        acceptLocationFeedState(locationFeed.state.value)
        when (event) {
            is LocationFeedEvent.Notice -> {
                _uiState.update { it.copy(followDevice = true, statusMessage = event.message) }
            }
            is LocationFeedEvent.Failed -> {
                _uiState.update {
                    it.copy(
                        followDevice = if (event.notice != null) true else it.followDevice,
                        statusMessage = event.notice ?: it.statusMessage,
                    )
                }
                showError(event.cause)
            }
        }
    }

    private fun acceptWalkTrackingState(walk: WalkTrackingState) {
        val previousWalkError = lastWalkError
        lastWalkError = walk.errorMessage

        _uiState.update { state ->
            val statusMessage = when {
                walk.errorMessage != null -> walk.errorMessage
                previousWalkError != null && state.statusMessage == previousWalkError -> null
                else -> state.statusMessage
            }
            state.copy(
                trail = walk.trail,
                statusMessage = statusMessage,
            )
        }
    }

    private fun beginPlaceDiscovery(
        origin: GeoPoint,
        intent: PlaceSearchIntent,
        originMode: PlaceOriginMode = PlaceOriginMode.DEVICE,
    ) {
        pendingPlaceIntent = null
        placeJourney.clear()
        _uiState.update {
            it.copy(locating = false, error = null)
        }
        placeDiscovery.search(origin, intent.kinds, intent.preferParking, originMode)
    }

    private fun showError(error: Throwable) {
        _uiState.update {
            it.copy(
                locating = false,
                error = error.message ?: "요청을 처리하지 못했습니다.",
            )
        }
    }

    class Factory(
        private val placeRepository: PlaceSearchRepository,
        private val journeyRepository: JourneyRepository,
        private val dogId: String,
        private val dogContext: DogSearchContext?,
        private val locationSource: LocationSource,
        private val territoryRepository: TerritoryRepository,
        private val walkTrackingController: WalkTrackingController,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            MapViewModel(
                placeRepository,
                journeyRepository,
                dogId,
                dogContext,
                locationSource,
                territoryRepository,
                walkTrackingController,
            ) as T
    }

}
