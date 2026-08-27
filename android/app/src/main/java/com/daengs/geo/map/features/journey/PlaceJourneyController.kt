package com.daengs.geo.map.features.journey

import com.daengs.geo.journey.JourneyItem
import com.daengs.geo.journey.JourneyRepository
import com.daengs.geo.journey.PlaceJourneyRequest
import com.daengs.geo.location.GeoPoint
import com.daengs.geo.place.PlaceKey
import com.daengs.geo.place.PlaceResult
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlin.math.abs

data class PlaceJourneyState(
    val destinationKey: PlaceKey? = null,
    val loading: Boolean = false,
    val item: JourneyItem? = null,
    val error: String? = null,
)

/** Owns one selected Place -> journey request and rejects stale responses after another click. */
class PlaceJourneyController(
    private val repository: JourneyRepository,
    private val dogId: String,
    private val scope: CoroutineScope,
) {
    private val mutableState = MutableStateFlow(PlaceJourneyState())
    val state: StateFlow<PlaceJourneyState> = mutableState.asStateFlow()

    private var lastRequest: PlaceJourneyRequest? = null
    private var requestGeneration = 0L

    fun load(origin: GeoPoint, place: PlaceResult) {
        submit(PlaceJourneyRequest(origin, place, dogId.trim().takeIf(String::isNotEmpty)))
    }

    fun retry() {
        lastRequest?.let(::submit) ?: run {
            mutableState.value = PlaceJourneyState(error = "다시 실행할 길찾기가 없습니다.")
        }
    }

    fun clear() {
        requestGeneration++
        lastRequest = null
        mutableState.value = PlaceJourneyState()
    }

    fun reject(destinationKey: PlaceKey, message: String) {
        requestGeneration++
        lastRequest = null
        mutableState.value = PlaceJourneyState(destinationKey = destinationKey, error = message)
    }

    private fun submit(request: PlaceJourneyRequest) {
        lastRequest = request
        val generation = ++requestGeneration
        mutableState.value = PlaceJourneyState(
            destinationKey = request.destinationKey,
            loading = true,
        )
        scope.launch {
            runCatching { repository.load(request) }
                .onSuccess { response ->
                    if (generation != requestGeneration) return@onSuccess
                    val item = response.items.singleOrNull()
                        ?.takeIf { journeyDestinationMatches(it, request) }
                    mutableState.value = PlaceJourneyState(
                        destinationKey = request.destinationKey,
                        item = item,
                        error = if (item != null) null else "길찾기 목적지를 확인할 수 없습니다.",
                    )
                }
                .onFailure { error ->
                    if (generation == requestGeneration) {
                        mutableState.value = PlaceJourneyState(
                            destinationKey = request.destinationKey,
                            error = error.message ?: "길찾기를 처리하지 못했습니다.",
                        )
                    }
                }
        }
    }
}

internal fun journeyDestinationMatches(item: JourneyItem, request: PlaceJourneyRequest): Boolean =
    abs(item.destination.latitude - request.destination.latitude) <= 0.000001 &&
        abs(item.destination.longitude - request.destination.longitude) <= 0.000001
