package com.daengs.geo.map

import com.daengs.geo.location.FeedStatus
import com.daengs.geo.location.GeoPoint
import com.daengs.geo.location.LocationSample
import com.daengs.geo.location.LocationSource
import com.daengs.geo.location.LocationTracker
import com.daengs.geo.location.ReplayLocationSource
import com.daengs.geo.walk.TrackingState
import com.daengs.geo.walk.WalkTrackingState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

enum class LocationFeed { DEVICE, REPLAY }

internal data class LocationFeedState(
    /** Last non-mock device fix. Search code may use this as a real current-location origin. */
    val deviceLocation: GeoPoint? = null,
    /** Last visible feed sample. Replay samples may appear here but never in [deviceLocation]. */
    val feedSample: LocationSample? = null,
    val feed: LocationFeed = LocationFeed.DEVICE,
)

internal sealed interface LocationFeedEvent {
    data class Notice(val message: String) : LocationFeedEvent

    data class Failed(
        val cause: Throwable,
        val notice: String? = null,
    ) : LocationFeedEvent
}

internal sealed interface LocationCommandResult {
    data class Accepted(val message: String? = null) : LocationCommandResult

    data class Rejected(val message: String) : LocationCommandResult
}

/**
 * Owns every screen-side continuous-location side effect.
 *
 * [MapViewModel] decides what a location is used for. This coordinator decides whether the screen,
 * replay, or [com.daengs.geo.walk.WalkTrackingService] may collect it, and is the only caller that
 * starts or stops [LocationTracker].
 */
internal class LocationFeedCoordinator(
    private val deviceLocationSource: LocationSource,
    private val walkState: StateFlow<WalkTrackingState>,
    private val scope: CoroutineScope,
    private val locationTimeoutMillis: Long = LOCATION_TIMEOUT_MS,
    private val replaySource: (GeoPoint, Double) -> LocationSource = { origin, speedMultiplier ->
        ReplayLocationSource(
            points = ReplayLocationSource.loopAround(origin),
            speedMultiplier = speedMultiplier,
        )
    },
) {
    private val tracker = LocationTracker(scope)
    private val mutableState = MutableStateFlow(LocationFeedState())
    val state: StateFlow<LocationFeedState> = mutableState.asStateFlow()

    private val eventChannel = Channel<LocationFeedEvent>(capacity = Channel.BUFFERED)
    val events = eventChannel.receiveAsFlow()

    private var appVisibility = AppVisibility.BACKGROUND
    private var activeSource: LocationSource? = null
    private var observedWalkState = walkState.value.trail.state

    init {
        scope.launch {
            tracker.updates.collect(::acceptLocation)
        }
        scope.launch {
            tracker.status.collect(::acceptFeedStatus)
        }
        scope.launch {
            walkState.collect(::acceptWalkState)
        }
    }

    /** A bounded one-shot device fix that also restores the visible feed to the real device. */
    suspend fun requestDeviceFix(): Result<LocationSample> = runCatching {
        withTimeoutOrNull(locationTimeoutMillis) { deviceLocationSource.currentLocation() }
            ?: throw IllegalStateException(
                "위치를 찾지 못했어요. 실내에서는 오래 걸릴 수 있어요 - " +
                    "창가로 나가거나 위치 설정을 확인한 뒤 다시 눌러주세요.",
            )
    }.onSuccess { sample ->
        switchFeed(LocationFeed.DEVICE, deviceLocationSource)
        acceptLocation(sample)
    }

    fun startReplay(speedMultiplier: Double): LocationCommandResult {
        if (!LocationOwnershipPolicy.canStartReplay(currentWalkState())) {
            return LocationCommandResult.Rejected("동선 기록 중에는 가상 이동을 시작할 수 없어요.")
        }
        val snapshot = mutableState.value
        val origin = snapshot.feedSample?.point ?: snapshot.deviceLocation ?: DEFAULT_REPLAY_ORIGIN
        switchFeed(LocationFeed.REPLAY, replaySource(origin, speedMultiplier))
        return LocationCommandResult.Accepted("가상 이동 ${speedMultiplier.toInt()}배속 재생 중")
    }

    fun onAppForeground() {
        if (appVisibility == AppVisibility.FOREGROUND) return
        appVisibility = AppVisibility.FOREGROUND
        val source = activeSource ?: return
        if (currentOwner().isScreenOwner) tracker.start(source)
    }

    fun onAppBackground(): String? {
        appVisibility = AppVisibility.BACKGROUND
        // This stops only the screen feed. WalkTrackingService owns recording independently.
        tracker.stop()
        return endReplay("화면을 벗어나 가상 이동을 종료했어요.")
    }

    /** Stop the screen subscriber before the service is told to start. */
    fun prepareWalkStart(): LocationCommandResult {
        if (!LocationOwnershipPolicy.canStartWalk(mutableState.value.feed)) {
            return LocationCommandResult.Rejected("실제 위치로 돌아온 뒤 동선 기록을 시작해주세요.")
        }
        tracker.stop()
        return LocationCommandResult.Accepted()
    }

    /** A resumed service takes the subscription before its next state emission reaches observers. */
    fun prepareWalkResume() {
        tracker.stop()
    }

    private fun switchFeed(feed: LocationFeed, source: LocationSource) {
        tracker.stop()
        activeSource = source
        mutableState.update {
            it.copy(
                feed = feed,
                feedSample = null,
            )
        }
        if (currentOwner().isScreenOwner) tracker.start(source)
    }

    private fun endReplay(message: String): String? {
        if (mutableState.value.feed != LocationFeed.REPLAY) return null
        switchFeed(LocationFeed.DEVICE, deviceLocationSource)
        return message
    }

    private fun acceptFeedStatus(status: FeedStatus) {
        when (status) {
            is FeedStatus.Failed -> {
                val notice = endReplay("가상 이동을 이어가지 못했어요.")
                eventChannel.trySend(LocationFeedEvent.Failed(status.cause, notice))
            }
            FeedStatus.Completed -> {
                endReplay("가상 이동 재생을 마쳤어요.")?.let { message ->
                    eventChannel.trySend(LocationFeedEvent.Notice(message))
                }
            }
            FeedStatus.Running, FeedStatus.Idle -> Unit
        }
    }

    private fun acceptLocation(sample: LocationSample) {
        mutableState.update { state ->
            state.copy(
                feedSample = sample,
                deviceLocation = if (sample.isMock) state.deviceLocation else sample.point,
            )
        }
    }

    private fun acceptWalkState(walk: WalkTrackingState) {
        val previous = observedWalkState
        observedWalkState = walk.trail.state

        val sample = walk.lastSample
        if (mutableState.value.feed == LocationFeed.DEVICE && sample != null) {
            acceptLocation(sample)
        }

        if (previous == walk.trail.state) return
        when (currentOwner(walk.trail.state)) {
            LocationOwner.WALK_SERVICE, LocationOwner.NONE -> tracker.stop()
            LocationOwner.SCREEN_DEVICE -> {
                val source = activeSource ?: deviceLocationSource.also { activeSource = it }
                tracker.start(source)
            }
            LocationOwner.SCREEN_REPLAY -> activeSource?.let(tracker::start)
        }
    }

    private fun currentWalkState(): TrackingState = walkState.value.trail.state

    private fun currentOwner(
        walk: TrackingState = currentWalkState(),
    ): LocationOwner = LocationOwnershipPolicy.owner(
        LocationOwnershipState(
            visibility = appVisibility,
            feed = mutableState.value.feed,
            walk = walk,
        ),
    )

    private companion object {
        val DEFAULT_REPLAY_ORIGIN = GeoPoint(latitude = 37.5665, longitude = 126.9780)

        /** A user-facing wait needs a finite end even if the platform callback never arrives. */
        const val LOCATION_TIMEOUT_MS = 15_000L
    }
}
