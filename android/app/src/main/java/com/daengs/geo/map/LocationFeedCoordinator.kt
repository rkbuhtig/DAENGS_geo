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
    private var activeSource: LocationSource? = deviceLocationSource.takeIf {
        walkState.value.trail.state != TrackingState.OFF
    }
    private var serviceHandoff = WalkServiceHandoff.NONE
    private var appliedOwner: LocationOwner? = null

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
        if (
            serviceHandoff != WalkServiceHandoff.NONE ||
            !LocationOwnershipPolicy.canStartReplay(currentWalkState())
        ) {
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
        reconcileOwnership()
    }

    fun onAppBackground(): String? {
        appVisibility = AppVisibility.BACKGROUND
        val replayNotice = endReplay("화면을 벗어나 가상 이동을 종료했어요.")
        if (replayNotice == null) reconcileOwnership()
        return replayNotice
    }

    /** Stop the screen subscriber before the service is told to start. */
    fun prepareWalkStart(): LocationCommandResult {
        if (serviceHandoff != WalkServiceHandoff.NONE) {
            return LocationCommandResult.Rejected("동선 기록 서비스를 시작하는 중이에요.")
        }
        if (currentWalkState() != TrackingState.OFF) {
            return LocationCommandResult.Rejected("이미 시작한 동선 기록 상태를 확인해주세요.")
        }
        if (!LocationOwnershipPolicy.canStartWalk(mutableState.value.feed)) {
            return LocationCommandResult.Rejected("실제 위치로 돌아온 뒤 동선 기록을 시작해주세요.")
        }
        serviceHandoff = WalkServiceHandoff.STARTING
        reconcileOwnership()
        return LocationCommandResult.Accepted()
    }

    /** A resumed service takes the subscription before its next state emission reaches observers. */
    fun prepareWalkResume(): LocationCommandResult {
        if (serviceHandoff != WalkServiceHandoff.NONE) {
            return LocationCommandResult.Rejected("동선 기록 서비스를 시작하는 중이에요.")
        }
        if (currentWalkState() != TrackingState.PAUSED) {
            return LocationCommandResult.Rejected("일시정지된 동선 기록이 없습니다.")
        }
        serviceHandoff = WalkServiceHandoff.RESUMING
        reconcileOwnership()
        return LocationCommandResult.Accepted()
    }

    /** Roll back only a command that failed before the service could acknowledge it. */
    fun cancelWalkHandoff() {
        if (serviceHandoff == WalkServiceHandoff.NONE) return
        serviceHandoff = WalkServiceHandoff.NONE
        reconcileOwnership()
    }

    private fun switchFeed(feed: LocationFeed, source: LocationSource) {
        tracker.stop()
        activeSource = source
        appliedOwner = null
        mutableState.update {
            it.copy(
                feed = feed,
                feedSample = null,
            )
        }
        reconcileOwnership()
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
        if (
            mutableState.value.feed == LocationFeed.DEVICE &&
            walk.trail.state != TrackingState.OFF &&
            activeSource == null
        ) {
            activeSource = deviceLocationSource
        }
        val sample = walk.lastSample
        if (mutableState.value.feed == LocationFeed.DEVICE && sample != null) {
            acceptLocation(sample)
        }

        if (
            serviceHandoff != WalkServiceHandoff.NONE &&
            (walk.trail.state == TrackingState.RECORDING || walk.errorMessage != null)
        ) {
            serviceHandoff = WalkServiceHandoff.NONE
        }
        reconcileOwnership(walk.trail.state)
    }

    private fun currentWalkState(): TrackingState = walkState.value.trail.state

    private fun currentOwner(
        walk: TrackingState = currentWalkState(),
    ): LocationOwner = LocationOwnershipPolicy.owner(
        LocationOwnershipState(
            visibility = appVisibility,
            feed = mutableState.value.feed,
            walk = walk,
            handoff = serviceHandoff,
        ),
    )

    /** Materialize the owner for the current state, including the first observed state. */
    private fun reconcileOwnership(walk: TrackingState = currentWalkState()) {
        val owner = currentOwner(walk)
        if (owner == appliedOwner) return
        when (owner) {
            LocationOwner.NONE,
            LocationOwner.WALK_SERVICE_PENDING,
            LocationOwner.WALK_SERVICE,
            -> tracker.stop()
            LocationOwner.SCREEN_DEVICE,
            LocationOwner.SCREEN_REPLAY,
            -> activeSource?.let(tracker::start)
        }
        appliedOwner = owner
    }

    private companion object {
        val DEFAULT_REPLAY_ORIGIN = GeoPoint(latitude = 37.5665, longitude = 126.9780)

        /** A user-facing wait needs a finite end even if the platform callback never arrives. */
        const val LOCATION_TIMEOUT_MS = 15_000L
    }
}
