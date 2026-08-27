package com.daengs.geo.map

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import com.daengs.geo.BuildConfig
import com.daengs.geo.ServerAddress
import com.daengs.geo.location.GeoPoint
import com.daengs.geo.map.features.places.DEFAULT_PLACE_KIND
import com.daengs.geo.map.features.places.PlaceDiscoveryPanel
import com.daengs.geo.map.features.places.canonicalPlaceKeysByMarker
import com.daengs.geo.map.features.places.canonicalPlaceMarkers
import com.daengs.geo.map.features.places.selectedPlaceKind
import com.daengs.geo.map.layers.territory.TerritoryLayerState
import com.daengs.geo.map.layers.trail.TrackingState
import com.daengs.geo.map.layers.trail.TrailLayerState
import com.daengs.geo.map.shell.MapHost
import com.daengs.geo.map.shell.MapScene
import com.daengs.geo.place.PlaceKey
import com.daengs.geo.place.PlaceKind
import com.daengs.geo.place.PlaceResult
import com.daengs.geo.walk.WalkExportShare
import java.io.File
import kotlin.math.abs
import kotlin.math.roundToInt
import kotlinx.coroutines.delay

private enum class AppSection { PLACES, MAP_TOOLS }

/** Consecutive dropped fixes before we admit on screen that recording is going nowhere. */
/** export 파일은 산책 종료 뒤 서비스 코루틴이 쓴다 — 생겼는지는 세어봐야 안다. */
private const val EXPORT_RECOUNT_MS = 2_000L

private const val LOW_ACCURACY_STREAK_TO_WARN = 3

@Composable
fun MapScreen(
    state: MapUiState,
    mapConfigured: Boolean,
    onCameraIdle: (GeoPoint) -> Unit,
    onCameraGesture: () -> Unit,
    onOpenHospital: () -> Unit,
    onSearchPlaces: (PlaceKind, Boolean) -> Unit,
    onSearchPlacesAtCamera: (PlaceKind, Boolean) -> Unit,
    onPlaceMyLocation: (PlaceKind, Boolean) -> Unit,
    onRetryPlaces: () -> Unit,
    onRetryLocation: () -> Unit,
    onSelectPlace: (PlaceKey) -> Unit,
    onJourney: (PlaceResult) -> Unit,
    onRetryJourney: () -> Unit,
    onOpenHandoff: (String) -> Unit,
    onCall: (String) -> Unit,
    onStartTracking: () -> Unit,
    onPauseTracking: () -> Unit,
    onResumeTracking: () -> Unit,
    onStopTracking: () -> Unit,
    onToggleTrail: () -> Unit,
    onToggleTerritory: () -> Unit,
    onClaimTerritory: () -> Unit,
    onStartReplay: (Double) -> Unit,
    onUseDeviceLocation: () -> Unit,
) {
    var section by remember { mutableStateOf(AppSection.PLACES) }
    val selectedKind = selectedPlaceKind(state.placeDiscovery)
    val canonicalMarkers = remember(state.placeDiscovery) {
        canonicalPlaceMarkers(state.placeDiscovery)
    }
    val canonicalKeys = remember(state.placeDiscovery.response) {
        canonicalPlaceKeysByMarker(state.placeDiscovery)
    }
    val places = when (section) {
        AppSection.PLACES -> canonicalMarkers
        AppSection.MAP_TOOLS -> emptyList()
    }
    val activeSearchOrigin = when (section) {
        AppSection.PLACES -> state.placeDiscovery.origin
        AppSection.MAP_TOOLS -> null
    }
    // 병원 바로가기도 같은 Place request lifecycle을 쓴다. 별도 hospital loading/error를
    // 다시 만들면 진입점 하나 때문에 검색 계약이 둘로 갈라진다.
    val sectionBusy = when (section) {
        AppSection.PLACES -> state.placeDiscovery.loading || state.locating
        AppSection.MAP_TOOLS -> state.locating
    }
    // A hidden layer hands the renderer nothing, so it cannot draw what is switched off.
    val trailLayer = remember(state.trail.segments, state.layers.showTrail) {
        TrailLayerState(
            paths = if (state.layers.showTrail) {
                state.trail.segments.map { segment -> segment.map { it.point } }
            } else {
                emptyList()
            },
        )
    }
    val territoryLayer = remember(
        state.territoryCells,
        state.currentTerritoryCell,
        state.layers.showTerritory,
    ) {
        if (state.layers.showTerritory) {
            TerritoryLayerState(
                claimedCells = state.territoryCells,
                previewCell = state.currentTerritoryCell,
            )
        } else {
            TerritoryLayerState()
        }
    }
    val scene = remember(state.feedSample, places, trailLayer, territoryLayer) {
        MapScene(
            currentPosition = state.feedSample?.point,
            places = places,
            trail = trailLayer,
            territory = territoryLayer,
        )
    }

    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        SectionTabs(
            section = section,
            selectedKind = selectedKind,
            onPlaces = {
                section = AppSection.PLACES
                if (selectedKind == PlaceKind.HOSPITAL) {
                    onSearchPlaces(DEFAULT_PLACE_KIND, false)
                }
            },
            onHospital = {
                section = AppSection.PLACES
                if (selectedKind != PlaceKind.HOSPITAL) onOpenHospital()
            },
            onMapTools = { section = AppSection.MAP_TOOLS },
        )
        Box(Modifier.fillMaxSize()) {
            if (mapConfigured) {
                MapHost(
                    scene = scene,
                    searchOrigin = activeSearchOrigin,
                    followDevice = state.followDevice,
                    onCameraIdle = onCameraIdle,
                    onCameraGesture = onCameraGesture,
                    onSelectPlace = { id ->
                        when (section) {
                            AppSection.PLACES -> canonicalKeys[id]?.let(onSelectPlace)
                            AppSection.MAP_TOOLS -> Unit
                        }
                    },
                    modifier = Modifier.fillMaxSize(),
                )
            } else {
                MissingMapConfiguration()
            }

            Column(
                modifier = Modifier.align(Alignment.TopCenter).padding(top = 12.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    val movedFromOrigin = canSearchMovedArea(
                        candidate = state.cameraCandidate,
                        origin = activeSearchOrigin,
                    )
                    if (section != AppSection.MAP_TOOLS && movedFromOrigin) {
                        Button(
                            onClick = {
                                when (section) {
                                    AppSection.PLACES -> onSearchPlacesAtCamera(
                                        selectedKind,
                                        state.placeDiscovery.preferParking,
                                    )
                                    AppSection.MAP_TOOLS -> Unit
                                }
                            },
                            enabled = !sectionBusy,
                        ) {
                            Text("이 지역 검색")
                        }
                    }
                    // 눌린 것이 **버튼 자리에서** 보여야 한다. 진행 표시가 지도 한가운데
                    // 있으면 시트에 가리거나 눈이 안 가서, 안 먹은 것과 구분이 안 된다.
                    val locating = state.locating
                    OutlinedButton(
                        onClick = {
                            when (section) {
                                AppSection.PLACES -> onPlaceMyLocation(
                                    selectedKind,
                                    state.placeDiscovery.preferParking,
                                )
                                AppSection.MAP_TOOLS -> onUseDeviceLocation()
                            }
                        },
                        enabled = !sectionBusy,
                    ) {
                        if (locating) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(16.dp),
                                strokeWidth = 2.dp,
                            )
                            Spacer(Modifier.width(8.dp))
                        }
                        Text(if (locating) "찾는 중" else "내 위치")
                    }
                }
                state.error?.let { error -> ErrorNotice(error = error, onRetry = onRetryLocation) }
            }

            when (section) {
                AppSection.PLACES -> PlaceDiscoveryPanel(
                    state = state.placeDiscovery,
                    journey = state.journey,
                    onSearch = onSearchPlaces,
                    onRetry = onRetryPlaces,
                    onSelect = onSelectPlace,
                    onJourney = onJourney,
                    onRetryJourney = onRetryJourney,
                    onOpenHandoff = onOpenHandoff,
                    onCall = onCall,
                    modifier = Modifier.align(Alignment.BottomCenter),
                )
                AppSection.MAP_TOOLS -> MapToolsPanel(
                    state = state,
                    onStartTracking = onStartTracking,
                    onPauseTracking = onPauseTracking,
                    onResumeTracking = onResumeTracking,
                    onStopTracking = onStopTracking,
                    onToggleTrail = onToggleTrail,
                    onToggleTerritory = onToggleTerritory,
                    onClaimTerritory = onClaimTerritory,
                    onStartReplay = onStartReplay,
                    onUseDeviceLocation = onUseDeviceLocation,
                    modifier = Modifier.align(Alignment.BottomCenter),
                )
            }

            if (state.locating) {
                Surface(
                    modifier = Modifier.align(Alignment.Center),
                    shape = RoundedCornerShape(18.dp),
                    tonalElevation = 8.dp,
                ) {
                    Row(Modifier.padding(18.dp), verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(modifier = Modifier.width(24.dp))
                        Spacer(Modifier.width(12.dp))
                        Text("현재 위치를 확인하는 중", style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
        }
    }
}

@Composable
private fun ErrorNotice(error: String, onRetry: () -> Unit) {
    Surface(
        modifier = Modifier.padding(horizontal = 16.dp),
        color = MaterialTheme.colorScheme.errorContainer,
        shape = RoundedCornerShape(12.dp),
        shadowElevation = 4.dp,
    ) {
        Column(Modifier.padding(12.dp)) {
            Text(error, maxLines = 3, overflow = TextOverflow.Ellipsis)
            TextButton(onClick = onRetry) { Text("다시 시도") }
        }
    }
}

@Composable
private fun SectionTabs(
    section: AppSection,
    selectedKind: PlaceKind,
    onPlaces: () -> Unit,
    onHospital: () -> Unit,
    onMapTools: () -> Unit,
) {
    Surface(shadowElevation = 3.dp) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp)) {
            listOf(
                Triple(
                    section == AppSection.PLACES && selectedKind != PlaceKind.HOSPITAL,
                    "장소",
                    onPlaces,
                ),
                Triple(
                    section == AppSection.PLACES && selectedKind == PlaceKind.HOSPITAL,
                    "동물병원",
                    onHospital,
                ),
                Triple(section == AppSection.MAP_TOOLS, "지도 기능", onMapTools),
            ).forEach { (selected, label, onClick) ->
                TextButton(onClick = onClick, modifier = Modifier.weight(1f)) {
                    Text(
                        label,
                        fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
                        color = if (selected) MaterialTheme.colorScheme.primary else Color.Gray,
                    )
                }
            }
        }
    }
}

@Composable
private fun MapToolsPanel(
    state: MapUiState,
    onStartTracking: () -> Unit,
    onPauseTracking: () -> Unit,
    onResumeTracking: () -> Unit,
    onStopTracking: () -> Unit,
    onToggleTrail: () -> Unit,
    onToggleTerritory: () -> Unit,
    onClaimTerritory: () -> Unit,
    onStartReplay: (Double) -> Unit,
    onUseDeviceLocation: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier.fillMaxWidth().heightIn(min = 180.dp, max = 370.dp),
        shape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp),
        shadowElevation = 12.dp,
    ) {
        LazyColumn(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            item {
                Column(Modifier.padding(top = 14.dp)) {
                    Box(
                        Modifier.width(42.dp).height(4.dp).clip(RoundedCornerShape(4.dp))
                            .background(Color(0xFFCBD3CD)).align(Alignment.CenterHorizontally),
                    )
                    Spacer(Modifier.height(10.dp))
                    Text("지도 레이어", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "${feedLabel(state.locationFeed)} · ${state.trail.sampleCount}개 점 · " +
                            formatMeters(state.trail.distanceMeters),
                        color = MaterialTheme.colorScheme.secondary,
                    )
                }
            }

            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    when (state.trail.state) {
                        TrackingState.OFF -> Button(onClick = onStartTracking) { Text("동선 기록 시작") }
                        TrackingState.RECORDING -> {
                            Button(onClick = onPauseTracking) { Text("일시정지") }
                            OutlinedButton(onClick = onStopTracking) { Text("종료") }
                        }
                        TrackingState.PAUSED -> {
                            Button(onClick = onResumeTracking) { Text("계속 기록") }
                            OutlinedButton(onClick = onStopTracking) { Text("종료") }
                        }
                    }
                    OutlinedButton(onClick = onToggleTrail) {
                        Text(if (state.layers.showTrail) "꼬리 숨기기" else "꼬리 보기")
                    }
                }
                if (BuildConfig.DEBUG) {
                    ServerAddressRow()
                }
                if (BuildConfig.DEBUG) {
                    WalkExportRow()
                }
                if (
                    state.trail.state == TrackingState.RECORDING &&
                    state.trail.skippedLowAccuracy >= LOW_ACCURACY_STREAK_TO_WARN
                ) {
                    Text(
                        "위치 정확도가 낮아 동선을 기록하지 못하고 있어요. " +
                            "설정에서 정확한 위치를 허용했는지 확인해주세요.",
                        style = MaterialTheme.typography.bodySmall,
                        color = Color(0xFF8A5A00),
                    )
                }
            }

            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilledTonalButton(onClick = onToggleTerritory) {
                        Text(if (state.layers.showTerritory) "영역 끄기" else "영역 켜기")
                    }
                    if (state.layers.showTerritory) {
                        Button(onClick = onClaimTerritory, enabled = state.feedSample != null) {
                            Text("현재 영역 마킹")
                        }
                    }
                }
                if (state.layers.showTerritory) {
                    Text(
                        "내 영역 ${state.territoryCells.size}개 · 주황색은 현재 위치",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                state.statusMessage?.let {
                    Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
                }
            }

            if (BuildConfig.DEBUG) {
                item {
                    Text("가상 이동", fontWeight = FontWeight.Bold)
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        listOf(1.0, 5.0, 10.0).forEach { speed ->
                            OutlinedButton(onClick = { onStartReplay(speed) }) {
                                Text("${speed.toInt()}×")
                            }
                        }
                        TextButton(onClick = onUseDeviceLocation) { Text("실제 위치") }
                    }
                }
            }
            item { Spacer(Modifier.height(8.dp)) }
        }
    }
}

@Composable
private fun MissingMapConfiguration() {
    Box(
        Modifier.fillMaxSize().background(Color(0xFFE4EAE5)).padding(28.dp),
        contentAlignment = Alignment.Center,
    ) {
        Surface(shape = RoundedCornerShape(18.dp)) {
            Column(Modifier.padding(20.dp)) {
                Text("네이버 지도 설정이 필요합니다", fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(6.dp))
                Text("android/local.properties에 DAENGS_NAVER_NCP_KEY_ID를 넣고 com.daengs.geo 패키지를 등록해주세요.")
            }
        }
    }
}

private fun canSearchMovedArea(candidate: GeoPoint?, origin: GeoPoint?): Boolean {
    candidate ?: return false
    origin ?: return false
    return abs(candidate.latitude - origin.latitude) > 0.0005 ||
        abs(candidate.longitude - origin.longitude) > 0.0005
}

private fun formatMeters(meters: Double): String {
    val rounded = meters.roundToInt()
    return if (rounded >= 1_000) "%.1fkm".format(rounded / 1_000.0) else "${rounded}m"
}

private fun feedLabel(feed: LocationFeed): String = when (feed) {
    LocationFeed.DEVICE -> "실제 위치"
    LocationFeed.REPLAY -> "가상 이동"
}


/**
 * 실측 도구. 종료한 산책의 원본 JSON 을 폰에서 바로 내보낸다.
 *
 * 이게 없으면 export 는 앱 내부 저장소에만 있어 `adb run-as` 로만 꺼낼 수 있다 — SDK 가 깔린
 * 그 PC 에 USB 로 꽂아야만 실측 데이터를 볼 수 있다는 뜻이다. 산책은 그 PC 에서 멀리 떨어져
 * 하는 일이므로, 폰이 스스로 보낼 수 있어야 한다.
 *
 * 몇 건이 대기 중인지 같이 보여준다. 내보내기는 종료 시 자동이라 화면에 흔적이 없었고,
 * "저장은 된 건가"를 확인할 방법이 로그뿐이었다.
 */
@Composable
private fun WalkExportRow() {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var exports by remember { mutableStateOf(emptyList<File>()) }

    // **화면에 떠 있는 동안 다시 센다.** resume 한 번으로는 부족하다 — 이 줄의 목적이
    // "종료 직후 바로 보내기"인데, 그때 앱은 계속 RESUMED 라 resume 이벤트가 오지 않는다.
    //
    // 산책 상태를 키로 쓰는 것도 안 된다. `WalkTrackingService.stopRecording()` 은 UI 상태를
    // 먼저 publish 하고(`store.publish`), export 는 그 뒤 `serviceScope.launch` 안에서
    // `writer.flush()` 다음에 일어난다. 상태가 OFF 로 바뀌는 시점엔 파일이 아직 없다.
    //
    // 파일이 언제 생기는지 UI 가 알 방법이 없어서 주기적으로 센다. 디버그 전용이고 세는 건
    // 작은 디렉터리의 `listFiles` 하나다.
    LaunchedEffect(lifecycleOwner) {
        lifecycleOwner.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            while (true) {
                exports = WalkExportShare.exports(context)
                delay(EXPORT_RECOUNT_MS)
            }
        }
    }

    Row(
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        OutlinedButton(
            enabled = exports.isNotEmpty(),
            onClick = {
                // 누르는 순간 다시 읽는다. 위 주기 사이에 산책이 끝났으면 그 파일도 같이 간다.
                val fresh = WalkExportShare.exports(context)
                exports = fresh
                WalkExportShare.shareIntent(context, fresh)?.let(context::startActivity)
            },
        ) {
            Text("산책 기록 보내기")
        }
        Text(
            // "대기"가 아니다 — 공유해도 파일은 남고 이 수는 줄지 않는다. 기기에 저장된 수다.
            if (exports.isEmpty()) "저장된 기록 없음" else "저장된 기록 ${exports.size}건",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.secondary,
        )
    }
}


/**
 * 개발 서버 주소. 빌드가 아니라 **여기서** 정한다.
 *
 * 개발 서버는 PC 안에 있어서 폰이 밖에서 부르려면 터널을 쓰는데, 그 주소가 자주 바뀐다.
 * 주소가 APK 에 박혀 있으면 바뀔 때마다 앱을 다시 만들어야 하고 그때까지 앱은 죽어 있다.
 * 붙여넣기 한 번으로 살아나야 한다.
 */
@Composable
private fun ServerAddressRow() {
    val context = LocalContext.current
    var editing by remember { mutableStateOf(false) }
    var url by remember { mutableStateOf(ServerAddress.current(context)) }
    var saved by remember { mutableStateOf(ServerAddress.current(context)) }
    var rejected by remember { mutableStateOf<String?>(null) }

    if (!editing) {
        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedButton(onClick = { url = saved; rejected = null; editing = true }) {
                Text("서버 주소")
            }
            Text(
                saved.removePrefix("https://").removePrefix("http://"),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.secondary,
            )
        }
        return
    }

    OutlinedTextField(
        value = url,
        onValueChange = { url = it; rejected = null },
        label = { Text("서버 주소") },
        placeholder = { Text("https://....trycloudflare.com") },
        singleLine = true,
        isError = rejected != null,
        supportingText = rejected?.let { { Text(it) } },
        modifier = Modifier.fillMaxWidth(),
    )
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = {
            when (val result = ServerAddress.set(context, url)) {
                is ServerAddress.Result.Rejected -> rejected = result.reason
                else -> {
                    saved = ServerAddress.current(context)
                    editing = false
                }
            }
        }) { Text("저장") }
        OutlinedButton(onClick = { editing = false }) { Text("취소") }
        // 터널을 접고 USB 로 돌아갈 때 필요하다. 빌드에 박힌 값으로 되돌린다.
        OutlinedButton(onClick = {
            ServerAddress.set(context, "")
            saved = ServerAddress.current(context)
            url = saved
            editing = false
        }) { Text("기본값") }
    }
}
