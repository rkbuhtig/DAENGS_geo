package com.daengs.geo.map.features.places

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.place.PlaceKey
import com.daengs.geo.place.PlaceKind
import com.daengs.geo.place.PlaceSearchRequest
import com.daengs.geo.place.PlaceSearchResponse
import com.daengs.geo.place.PlaceSearchRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class PlaceDiscoveryState(
    val requestedKinds: List<PlaceKind> = emptyList(),
    val origin: GeoPoint? = null,
    val preferParking: Boolean = false,
    val response: PlaceSearchResponse? = null,
    val selectedPlaceKey: PlaceKey? = null,
    val loading: Boolean = false,
    val error: String? = null,
)

/**
 * Owns canonical Place request lifecycle so MapViewModel does not absorb another feature's
 * request construction, retry memory, and stale-response rules.
 */
class PlaceDiscoveryController(
    private val repository: PlaceSearchRepository,
    private val dogId: String,
    private val scope: CoroutineScope,
) {
    private val mutableState = MutableStateFlow(PlaceDiscoveryState())
    val state: StateFlow<PlaceDiscoveryState> = mutableState.asStateFlow()

    private var lastRequest: PlaceSearchRequest? = null
    private var requestGeneration = 0L

    fun search(
        origin: GeoPoint,
        kinds: List<PlaceKind>,
        preferParking: Boolean = false,
    ) {
        submit(
            PlaceSearchRequest(
                origin = origin,
                kinds = kinds,
                dogId = dogId.takeIf(String::isNotBlank),
                preferParking = preferParking,
            ),
        )
    }

    fun retry() {
        val request = lastRequest
        if (request == null) {
            mutableState.update { it.copy(error = "다시 실행할 장소 검색이 없습니다.") }
            return
        }
        submit(request)
    }

    fun select(key: PlaceKey) {
        mutableState.update { it.copy(selectedPlaceKey = key) }
    }

    private fun submit(request: PlaceSearchRequest) {
        lastRequest = request
        val generation = ++requestGeneration
        mutableState.value = PlaceDiscoveryState(
            requestedKinds = request.kinds,
            origin = request.origin,
            preferParking = request.preferParking,
            loading = true,
        )
        scope.launch {
            runCatching { repository.search(request) }
                .onSuccess { response ->
                    if (generation != requestGeneration) return@onSuccess
                    mutableState.update {
                        it.copy(
                            response = response,
                            selectedPlaceKey = response.firstPlaceKey(),
                            loading = false,
                            error = null,
                        )
                    }
                }
                .onFailure { error ->
                    if (generation == requestGeneration) {
                        mutableState.update {
                            it.copy(
                                loading = false,
                                error = error.message ?: "장소 검색을 처리하지 못했습니다.",
                            )
                        }
                    }
                }
        }
    }
}

private fun PlaceSearchResponse.firstPlaceKey(): PlaceKey? = groups.asSequence()
    .flatMap { it.results.asSequence() }
    .firstOrNull()
    ?.place
    ?.key
