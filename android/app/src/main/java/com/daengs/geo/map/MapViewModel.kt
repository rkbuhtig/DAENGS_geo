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
import com.daengs.geo.map.layers.trail.TrailRecorder
import com.daengs.geo.map.layers.trail.TrailSnapshot
import com.daengs.geo.territory.ClaimRejectReason
import com.daengs.geo.territory.ClaimResult
import com.daengs.geo.territory.TerritoryCell
import com.daengs.geo.territory.TerritoryRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray

enum class LocationFeed { DEVICE, REPLAY }

data class MapLayerPreferences(
    val showTrail: Boolean = true,
    val showTerritory: Boolean = false,
)

data class MapUiState(
    /**
     * Where the user actually is. Only a real device fix ever writes this, because it is what a
     * FOLLOW_DEVICE search sends as its origin and what the "내 위치 기준" label promises.
     */
    val deviceLocation: GeoPoint? = null,
    /**
     * What the live feed says, replay included. Camera, trail and territory read this; the
     * hospital search never does.
     */
    val feedSample: LocationSample? = null,
    val searchOrigin: GeoPoint? = null,
    val cameraCandidate: GeoPoint? = null,
    val followDevice: Boolean = true,
    val locationMode: LocationMode = LocationMode.FOLLOW_DEVICE,
    val locationFeed: LocationFeed = LocationFeed.DEVICE,
    val response: HospitalSearchResponse? = null,
    val selectedHospitalId: Long? = null,
    val trail: TrailSnapshot = TrailSnapshot(),
    val layers: MapLayerPreferences = MapLayerPreferences(),
    val territoryCells: List<TerritoryCell> = emptyList(),
    val currentTerritoryCell: TerritoryCell? = null,
    val statusMessage: String? = null,
    val loading: Boolean = false,
    val error: String? = null,
)

class MapViewModel(
    private val hospitalRepository: HospitalRepository,
    private val deviceLocationSource: LocationSource,
    private val territoryRepository: TerritoryRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(MapUiState())
    val uiState: StateFlow<MapUiState> = _uiState.asStateFlow()

    private val locationTracker = LocationTracker(viewModelScope)
    private val trailRecorder = TrailRecorder()

    /** The subscription may only run while the Activity is on screen: there is no service yet. */
    private var isForeground = false
    private var activeSource: LocationSource? = null

    init {
        viewModelScope.launch {
            locationTracker.updates.collect(::acceptLocation)
        }
        viewModelScope.launch {
            locationTracker.status.collect(::onFeedStatus)
        }
        viewModelScope.launch {
            territoryRepository.claimedCells.collect { cells ->
                _uiState.update { it.copy(territoryCells = cells) }
            }
        }
    }

    fun locateAndSearch() {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, error = null) }
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
            _uiState.update { it.copy(loading = true, error = null) }
            if (fetchDeviceFix() == null) return@launch
            _uiState.update {
                it.copy(loading = false, statusMessage = "실제 기기 위치를 사용합니다.")
            }
        }
    }

    fun startReplay(speedMultiplier: Double) {
        val state = _uiState.value
        val origin = state.feedSample?.point ?: state.deviceLocation ?: DEFAULT_REPLAY_ORIGIN
        val source = ReplayLocationSource(
            points = ReplayLocationSource.loopAround(origin),
            speedMultiplier = speedMultiplier,
        )
        // Replay is a debug fixture: it swaps the feed and never touches what the user recorded.
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
        isForeground = true
        val source = activeSource ?: return
        if (_uiState.value.locationFeed == LocationFeed.DEVICE) locationTracker.start(source)
    }

    fun onAppBackground() {
        isForeground = false
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
        if (_uiState.value.response == null) locateAndSearch() else search()
    }

    fun selectHospital(id: Long) {
        _uiState.update { it.copy(selectedHospitalId = id) }
    }

    fun startTracking() {
        _uiState.update { it.copy(trail = trailRecorder.start()) }
    }

    fun pauseTracking() {
        _uiState.update { it.copy(trail = trailRecorder.pause()) }
    }

    fun resumeTracking() {
        _uiState.update { it.copy(trail = trailRecorder.resume()) }
    }

    fun stopTracking() {
        _uiState.update { it.copy(trail = trailRecorder.stop()) }
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

    private suspend fun fetchDeviceFix(): LocationSample? =
        runCatching { deviceLocationSource.currentLocation() }
            .onSuccess { sample ->
                switchFeed(LocationFeed.DEVICE, deviceLocationSource, statusMessage = null)
                acceptLocation(sample)
            }
            .onFailure(::showError)
            .getOrNull()

    /**
     * The only place a feed starts. Every caller goes through here so the tracker cannot be
     * revived while backgrounded and a feed change cannot stitch two trails together.
     */
    private fun switchFeed(
        feed: LocationFeed,
        source: LocationSource,
        statusMessage: String?,
    ) {
        locationTracker.stop()
        if (_uiState.value.locationFeed != feed) trailRecorder.breakSegment()
        activeSource = source
        _uiState.update {
            it.copy(
                locationFeed = feed,
                feedSample = null,
                followDevice = true,
                trail = trailRecorder.snapshot(),
                statusMessage = statusMessage,
            )
        }
        if (isForeground) locationTracker.start(source)
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
        val trail = trailRecorder.add(sample)
        _uiState.update { state ->
            state.copy(
                feedSample = sample,
                deviceLocation = if (sample.isMock) state.deviceLocation else sample.point,
                trail = trail,
                currentTerritoryCell = if (state.layers.showTerritory) {
                    territoryRepository.cellAt(sample.point)
                } else {
                    null
                },
            )
        }
    }

    private fun search(edits: JsonArray = JsonArray(emptyList())) {
        val before = _uiState.value
        val session = SearchSession(
            state = before.response?.state,
            deviceLocation = before.deviceLocation,
            mode = before.locationMode,
        )
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, error = null) }
            runCatching {
                hospitalRepository.search(SearchRequestBuilder.build(session, edits))
            }.onSuccess { response ->
                _uiState.update {
                    it.copy(
                        response = response,
                        searchOrigin = response.origin,
                        selectedHospitalId = response.results.firstOrNull()?.id,
                        loading = false,
                        error = null,
                    )
                }
            }.onFailure(::showError)
        }
    }

    private fun showError(error: Throwable) {
        _uiState.update {
            it.copy(
                loading = false,
                error = error.message ?: "요청을 처리하지 못했습니다.",
            )
        }
    }

    class Factory(
        private val hospitalRepository: HospitalRepository,
        private val locationSource: LocationSource,
        private val territoryRepository: TerritoryRepository,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            MapViewModel(hospitalRepository, locationSource, territoryRepository) as T
    }

    companion object {
        private val DEFAULT_REPLAY_ORIGIN = GeoPoint(latitude = 37.5665, longitude = 126.9780)
    }
}
