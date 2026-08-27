package com.daengs.geo.map.features.places

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.place.PlaceKey
import com.daengs.geo.place.PlaceKind
import com.daengs.geo.place.PlaceSearchRequest
import com.daengs.geo.place.PlaceSearchResponse
import com.daengs.geo.place.PlaceSearchRepository
import com.daengs.geo.place.supportsParkingPreference
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** 결과가 어느 지점 기준인지. 화면 문구와 "종류만 바꾸기"가 같은 사실을 봐야 한다. */
enum class PlaceOriginMode { DEVICE, PINNED }

data class PlaceDiscoveryState(
    val requestedKinds: List<PlaceKind> = emptyList(),
    val origin: GeoPoint? = null,
    val originMode: PlaceOriginMode = PlaceOriginMode.DEVICE,
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
    private var lastOriginMode = PlaceOriginMode.DEVICE
    private var requestGeneration = 0L

    fun search(
        origin: GeoPoint,
        kinds: List<PlaceKind>,
        preferParking: Boolean = false,
        originMode: PlaceOriginMode = PlaceOriginMode.DEVICE,
    ) {
        submit(
            PlaceSearchRequest(
                origin = origin,
                kinds = kinds,
                dogId = dogId.takeIf(String::isNotBlank),
                // 주차 사실 계약이 없는 kind만 요청했다면 선호를 들고 가지 않는다. 화면에서
                // 칩이 사라진 뒤에도 이전 선택이 몰래 따라붙던 자리다.
                preferParking = preferParking && kinds.any(PlaceKind::supportsParkingPreference),
            ),
            originMode,
        )
    }

    fun retry() {
        val request = lastRequest
        if (request == null) {
            mutableState.update { it.copy(error = "다시 실행할 장소 검색이 없습니다.") }
            return
        }
        submit(request, lastOriginMode)
    }

    fun select(key: PlaceKey) {
        mutableState.update { it.copy(selectedPlaceKey = key) }
    }

    private fun submit(request: PlaceSearchRequest, originMode: PlaceOriginMode) {
        lastRequest = request
        lastOriginMode = originMode
        val generation = ++requestGeneration
        mutableState.value = PlaceDiscoveryState(
            requestedKinds = request.kinds,
            origin = request.origin,
            originMode = originMode,
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
