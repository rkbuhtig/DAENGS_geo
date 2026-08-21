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
import com.daengs.geo.location.LocationSource
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray

data class HospitalMapUiState(
    val deviceLocation: GeoPoint? = null,
    val searchOrigin: GeoPoint? = null,
    val cameraCandidate: GeoPoint? = null,
    val locationMode: LocationMode = LocationMode.FOLLOW_DEVICE,
    val response: HospitalSearchResponse? = null,
    val selectedHospitalId: Long? = null,
    val loading: Boolean = false,
    val error: String? = null,
)

class HospitalMapViewModel(
    private val repository: HospitalRepository,
    private val locationSource: LocationSource,
) : ViewModel() {
    private val _uiState = MutableStateFlow(HospitalMapUiState())
    val uiState: StateFlow<HospitalMapUiState> = _uiState.asStateFlow()

    fun locateAndSearch() {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, error = null) }
            runCatching { locationSource.currentLocation() }
                .onSuccess { point ->
                    _uiState.update {
                        it.copy(
                            deviceLocation = point,
                            locationMode = LocationMode.FOLLOW_DEVICE,
                            cameraCandidate = point,
                        )
                    }
                    search()
                }
                .onFailure(::showError)
        }
    }

    fun onCameraIdle(point: GeoPoint) {
        _uiState.update { it.copy(cameraCandidate = point) }
    }

    fun searchPinnedArea() {
        val state = _uiState.value
        val point = state.cameraCandidate ?: return
        if (state.response == null) return
        _uiState.update { it.copy(locationMode = LocationMode.PINNED) }
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
                repository.search(SearchRequestBuilder.build(session, edits))
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
        private val repository: HospitalRepository,
        private val locationSource: LocationSource,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            HospitalMapViewModel(repository, locationSource) as T
    }
}
