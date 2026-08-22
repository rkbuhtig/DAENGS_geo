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
import com.daengs.geo.location.GeoPoint
import com.daengs.geo.location.LocationSample
import com.daengs.geo.location.LocationSource
import com.daengs.geo.location.LocationTracker
import com.daengs.geo.location.ReplayLocationSource
import com.daengs.geo.map.layers.trail.TrailRecorder
import com.daengs.geo.map.layers.trail.TrailSnapshot
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
    val deviceLocation: GeoPoint? = null,
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
    private var latestSample: LocationSample? = null

    init {
        viewModelScope.launch {
            locationTracker.updates.collect(::acceptLocation)
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
            runCatching { deviceLocationSource.currentLocation() }
                .onSuccess { sample ->
                    _uiState.update {
                        it.copy(
                            locationMode = LocationMode.FOLLOW_DEVICE,
                            locationFeed = LocationFeed.DEVICE,
                            followDevice = true,
                            cameraCandidate = sample.point,
                        )
                    }
                    acceptLocation(sample)
                    locationTracker.start(deviceLocationSource)
                    search()
                }
                .onFailure(::showError)
        }
    }

    fun onCameraIdle(point: GeoPoint) {
        _uiState.update { it.copy(cameraCandidate = point) }
    }

    fun onCameraGesture() {
        _uiState.update { it.copy(followDevice = false) }
    }

    fun onAppForeground() {
        val state = _uiState.value
        if (state.deviceLocation != null && state.locationFeed == LocationFeed.DEVICE) {
            locationTracker.start(deviceLocationSource)
        }
    }

    fun onAppBackground() {
        locationTracker.stop()
        if (_uiState.value.locationFeed == LocationFeed.REPLAY) {
            _uiState.update {
                it.copy(
                    locationFeed = LocationFeed.DEVICE,
                    statusMessage = "화면을 벗어나 가상 이동을 종료했어요.",
                )
            }
        }
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
        _uiState.update { it.copy(trail = trailRecorder.start(clearPrevious = true)) }
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
            state.copy(
                layers = state.layers.copy(showTerritory = !state.layers.showTerritory),
                statusMessage = null,
            )
        }
    }

    fun claimCurrentCell() {
        viewModelScope.launch {
            val result = territoryRepository.claim(latestSample)
            val message = when (result) {
                is ClaimResult.Claimed -> "이 영역을 내 지도에 표시했어요."
                is ClaimResult.AlreadyClaimed -> "이미 표시한 영역이에요."
                is ClaimResult.Rejected -> "현재 위치를 확인한 뒤 다시 시도해주세요."
            }
            _uiState.update { it.copy(statusMessage = message) }
        }
    }

    fun startReplay(speedMultiplier: Double) {
        val origin = latestSample?.point ?: _uiState.value.deviceLocation ?: DEFAULT_REPLAY_ORIGIN
        val source = ReplayLocationSource(
            points = ReplayLocationSource.loopAround(origin),
            speedMultiplier = speedMultiplier,
        )
        trailRecorder.start(clearPrevious = true)
        _uiState.update {
            it.copy(
                locationFeed = LocationFeed.REPLAY,
                followDevice = true,
                trail = trailRecorder.snapshot(),
                statusMessage = "가상 이동 ${speedMultiplier.toInt()}배속 재생 중",
            )
        }
        locationTracker.start(source)
    }

    fun useDeviceLocation() {
        viewModelScope.launch {
            runCatching { deviceLocationSource.currentLocation() }
                .onSuccess { sample ->
                    acceptLocation(sample)
                    _uiState.update {
                        it.copy(
                            locationFeed = LocationFeed.DEVICE,
                            followDevice = true,
                            statusMessage = "실제 기기 위치를 사용합니다.",
                        )
                    }
                    locationTracker.start(deviceLocationSource)
                }
                .onFailure(::showError)
        }
    }

    private fun acceptLocation(sample: LocationSample) {
        latestSample = sample
        val trail = trailRecorder.add(sample)
        _uiState.update {
            it.copy(
                deviceLocation = sample.point,
                trail = trail,
                currentTerritoryCell = territoryRepository.cellAt(sample.point),
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
