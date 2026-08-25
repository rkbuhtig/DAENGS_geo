package com.daengs.geo.map

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import com.daengs.geo.hospital.HospitalResult
import com.daengs.geo.hospital.LocationMode
import com.daengs.geo.hospital.SuggestedAction
import com.daengs.geo.location.GeoPoint
import com.daengs.geo.map.layers.places.PlaceMarkerState
import com.daengs.geo.map.layers.territory.TerritoryLayerState
import com.daengs.geo.map.layers.trail.TrackingState
import com.daengs.geo.map.layers.trail.TrailLayerState
import com.daengs.geo.map.shell.MapHost
import com.daengs.geo.map.shell.MapScene
import com.daengs.geo.walk.WalkExportShare
import java.io.File
import kotlin.math.abs
import kotlin.math.roundToInt
import kotlinx.coroutines.delay

private enum class AppSection { HOSPITAL, MAP_TOOLS }

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
    onSearchArea: () -> Unit,
    onMyLocation: () -> Unit,
    onAction: (SuggestedAction) -> Unit,
    onRetry: () -> Unit,
    onHundredMeters: () -> Unit,
    onSelectHospital: (Long) -> Unit,
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
    var section by remember { mutableStateOf(AppSection.HOSPITAL) }
    val places = remember(state.response, state.selectedHospitalId) {
        state.response?.results.orEmpty().map { hospital ->
            PlaceMarkerState(
                id = hospital.id.toString(),
                point = hospital.point,
                label = hospital.name,
                selected = hospital.id == state.selectedHospitalId,
                iconGroup = hospital.iconGroup,
            )
        }
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
        SectionTabs(section = section, onSection = { section = it })
        Box(Modifier.fillMaxSize()) {
            if (mapConfigured) {
                MapHost(
                    scene = scene,
                    searchOrigin = state.searchOrigin,
                    followDevice = state.followDevice,
                    onCameraIdle = onCameraIdle,
                    onCameraGesture = onCameraGesture,
                    onSelectPlace = { id -> id.toLongOrNull()?.let(onSelectHospital) },
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
                    if (section == AppSection.HOSPITAL && canSearchMovedArea(state)) {
                        Button(onClick = onSearchArea) { Text("이 지역 검색") }
                    }
                    OutlinedButton(onClick = onMyLocation) { Text("내 위치") }
                }
                // Errors belong to the app, not to one tab: a location failure raised from the
                // map tools used to be invisible until the user wandered back to the hospital tab.
                state.error?.let { error -> ErrorNotice(error = error, onRetry = onRetry) }
            }

            if (section == AppSection.HOSPITAL) {
                SearchPanel(
                    state = state,
                    onAction = onAction,
                    onHundredMeters = onHundredMeters,
                    onSelectHospital = onSelectHospital,
                    onCall = onCall,
                    modifier = Modifier.align(Alignment.BottomCenter),
                )
            } else {
                MapToolsPanel(
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

            if (state.loading) {
                Surface(
                    modifier = Modifier.align(Alignment.Center),
                    shape = RoundedCornerShape(18.dp),
                    tonalElevation = 8.dp,
                ) {
                    Row(Modifier.padding(18.dp), verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(modifier = Modifier.width(24.dp))
                        Spacer(Modifier.width(12.dp))
                        Text("주변 병원을 찾는 중")
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
private fun SectionTabs(section: AppSection, onSection: (AppSection) -> Unit) {
    Surface(shadowElevation = 3.dp) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp)) {
            listOf(AppSection.HOSPITAL to "병원", AppSection.MAP_TOOLS to "지도 기능").forEach { (item, label) ->
                TextButton(onClick = { onSection(item) }, modifier = Modifier.weight(1f)) {
                    Text(
                        label,
                        fontWeight = if (section == item) FontWeight.Bold else FontWeight.Normal,
                        color = if (section == item) MaterialTheme.colorScheme.primary else Color.Gray,
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
private fun SearchPanel(
    state: MapUiState,
    onAction: (SuggestedAction) -> Unit,
    onHundredMeters: () -> Unit,
    onSelectHospital: (Long) -> Unit,
    onCall: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier.fillMaxWidth().heightIn(min = 150.dp, max = 360.dp),
        shape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp),
        shadowElevation = 12.dp,
    ) {
        LazyColumn(
            modifier = Modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            item {
                Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 14.dp)) {
                    Box(
                        Modifier.width(42.dp).height(4.dp).clip(RoundedCornerShape(4.dp))
                            .background(Color(0xFFCBD3CD)).align(Alignment.CenterHorizontally),
                    )
                    Spacer(Modifier.height(10.dp))
                    Text(
                        state.response?.reply ?: "위치를 확인하면 주변 병원을 보여드릴게요.",
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Text(
                        if (state.locationMode == LocationMode.PINNED) "지도를 움직인 위치 기준" else "내 위치 기준",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.secondary,
                    )
                }
            }

            val response = state.response
            if (response?.showCallCta == true || response?.resolution?.any { it.overrode.isNotBlank() } == true) {
                item { SafetyNotice(state = state) }
            }

            if (!response?.actions.isNullOrEmpty()) {
                item {
                    LazyRow(
                        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        items(response.actions, key = { it.id }) { action ->
                            FilledTonalButton(onClick = { onAction(action) }) { Text(action.label) }
                        }
                    }
                }
            }

            if (response != null && response.results.isEmpty()) {
                item {
                    Text(
                        "조건에 맞는 병원이 없습니다. 위 제안으로 조건을 바꿔볼 수 있어요.",
                        modifier = Modifier.padding(horizontal = 16.dp),
                    )
                }
            } else if (response != null) {
                item {
                    LazyRow(
                        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp),
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        items(response.results, key = { it.id }) { hospital ->
                            HospitalCard(
                                hospital = hospital,
                                selected = hospital.id == state.selectedHospitalId,
                                onSelect = { onSelectHospital(hospital.id) },
                                onCall = onCall,
                            )
                        }
                    }
                }
            }

            if (BuildConfig.DEBUG && response != null) {
                item {
                    TextButton(
                        onClick = onHundredMeters,
                        modifier = Modifier.padding(horizontal = 12.dp),
                    ) {
                        Text("CTA 확인용 · 반경 100m")
                    }
                }
            }
            item { Spacer(Modifier.height(8.dp)) }
        }
    }
}

@Composable
private fun SafetyNotice(state: MapUiState) {
    val response = state.response ?: return
    val overrides = response.resolution.filter { it.overrode.isNotBlank() }
    Surface(
        modifier = Modifier.padding(horizontal = 16.dp),
        color = Color(0xFFFFE9C6),
        shape = RoundedCornerShape(12.dp),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            if (response.showCallCta) {
                Text("방문 전 병원에 전화해 확인하세요", fontWeight = FontWeight.Bold)
                response.callReasons.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
            }
            overrides.forEach { notice ->
                Text("${notice.overrode}: ${notice.because.ifBlank { notice.what }}")
            }
        }
    }
}

@Composable
private fun HospitalCard(
    hospital: HospitalResult,
    selected: Boolean,
    onSelect: () -> Unit,
    onCall: (String) -> Unit,
) {
    val border = if (selected) MaterialTheme.colorScheme.primary else Color(0xFFDDE3DF)
    Surface(
        modifier = Modifier.width(292.dp).border(1.dp, border, RoundedCornerShape(16.dp))
            .clickable(onClick = onSelect),
        shape = RoundedCornerShape(16.dp),
        color = Color.White,
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Text(hospital.name, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                "${formatMeters(hospital.distanceMeters)} · ${openLabel(hospital.openNow)}",
                color = if (hospital.openNow == null) Color(0xFF8A5A00) else MaterialTheme.colorScheme.secondary,
            )
            hospital.walk?.let { walk ->
                val route = when (walk.status) {
                    "measured" -> "도보 실측 ${walk.minutes ?: "?"}분"
                    "estimate" -> "도보 추정 ${walk.minutes ?: "?"}분"
                    else -> "도보 경로 확인 불가"
                }
                Text(route, style = MaterialTheme.typography.bodySmall)
            }
            hospital.address?.let { Text(it, maxLines = 1, overflow = TextOverflow.Ellipsis) }
            if (hospital.preferHits.isNotEmpty()) {
                Text(
                    "병원명에서 ${hospital.preferHits.joinToString(" · ")} 관련 표현 감지",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            hospital.phone?.let { phone ->
                OutlinedButton(onClick = { onCall(phone) }, modifier = Modifier.fillMaxWidth()) {
                    Text("전화 $phone")
                }
            }
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

private fun canSearchMovedArea(state: MapUiState): Boolean {
    val candidate = state.cameraCandidate ?: return false
    val origin = state.searchOrigin ?: return false
    return abs(candidate.latitude - origin.latitude) > 0.0005 ||
        abs(candidate.longitude - origin.longitude) > 0.0005
}

private fun openLabel(openNow: Boolean?): String = when (openNow) {
    true -> "영업 확인"
    false -> "영업 종료"
    null -> "영업시간 미상 · 전화 확인"
}

private fun formatMeters(meters: Int): String =
    if (meters >= 1_000) "%.1fkm".format(meters / 1_000.0) else "${meters}m"

private fun formatMeters(meters: Double): String = formatMeters(meters.roundToInt())

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
