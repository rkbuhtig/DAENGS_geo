package com.daengs.geo.map.features.places

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.daengs.geo.map.layers.places.PlaceMarkerState
import com.daengs.geo.place.BooleanFactCoverage
import com.daengs.geo.place.DogAccessState
import com.daengs.geo.place.PlaceKey
import com.daengs.geo.place.PlaceKind
import com.daengs.geo.place.PlaceSearchGroup
import com.daengs.geo.place.PlaceSearchHit
import com.daengs.geo.place.PlaceSortType

data class PlaceCategory(
    val kind: PlaceKind,
    val label: String,
)

data class DogAccessCoverage(
    val compatible: Int,
    val incompatible: Int,
    val unknown: Int,
)

/** Exact canonical kinds, not inferred leisure/errand axes. One chip means one server group. */
val PLACE_CATEGORIES = listOf(
    PlaceCategory(PlaceKind.CAFE, "카페"),
    PlaceCategory(PlaceKind.RESTAURANT, "음식점"),
    PlaceCategory(PlaceKind.PET_SHOP, "펫샵"),
    PlaceCategory(PlaceKind.SHOPPING, "일반 쇼핑"),
    PlaceCategory(PlaceKind.GROOMING, "미용"),
    PlaceCategory(PlaceKind.BOARDING, "위탁"),
    PlaceCategory(PlaceKind.HOSPITAL, "병원"),
    PlaceCategory(PlaceKind.PHARMACY, "약국"),
    PlaceCategory(PlaceKind.TRAVEL, "여행지"),
    PlaceCategory(PlaceKind.LEISURE, "레저"),
    PlaceCategory(PlaceKind.PENSION, "펜션"),
    PlaceCategory(PlaceKind.HOTEL, "호텔"),
    PlaceCategory(PlaceKind.STAY, "숙박"),
    PlaceCategory(PlaceKind.MUSEUM, "박물관"),
    PlaceCategory(PlaceKind.GALLERY, "미술관"),
    PlaceCategory(PlaceKind.ARTS_CENTER, "문예회관"),
    PlaceCategory(PlaceKind.CULTURE, "문화시설"),
    PlaceCategory(PlaceKind.ETC, "기타"),
)

val DEFAULT_PLACE_KIND = PlaceKind.CAFE

fun selectedPlaceKind(state: PlaceDiscoveryState): PlaceKind =
    state.requestedKinds.singleOrNull() ?: DEFAULT_PLACE_KIND

fun canonicalPlaceMarkers(state: PlaceDiscoveryState): List<PlaceMarkerState> =
    state.response?.groups.orEmpty().flatMap { group ->
        group.results.map { hit ->
            PlaceMarkerState(
                id = placeMarkerId(hit.place.key),
                point = hit.place.point,
                label = hit.place.name,
                selected = hit.place.key == state.selectedPlaceKey,
                iconGroup = hit.place.iconGroup,
            )
        }
    }

fun canonicalPlaceKeysByMarker(state: PlaceDiscoveryState): Map<String, PlaceKey> =
    state.response?.groups.orEmpty().flatMap(PlaceSearchGroup::results)
        .associate { hit -> placeMarkerId(hit.place.key) to hit.place.key }

/** Length-prefix keeps `(source, ref)` opaque and collision-free without parsing source contents. */
fun placeMarkerId(key: PlaceKey): String = "place:${key.source.length}:${key.source}${key.ref}"

@Composable
fun PlaceDiscoveryPanel(
    state: PlaceDiscoveryState,
    onSearch: (PlaceKind, Boolean) -> Unit,
    onRetry: () -> Unit,
    onSelect: (PlaceKey) -> Unit,
    onCall: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val selectedKind = selectedPlaceKind(state)
    val group = state.response?.groups?.singleOrNull()
        ?: state.response?.groups?.firstOrNull()

    Surface(
        modifier = modifier.fillMaxWidth().heightIn(min = 210.dp, max = 430.dp),
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
                        Modifier.width(42.dp).height(4.dp)
                            .background(Color(0xFFCBD3CD), RoundedCornerShape(4.dp))
                            .align(Alignment.CenterHorizontally),
                    )
                    Spacer(Modifier.height(10.dp))
                    Text("내 주변 장소", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "카테고리 하나씩 사실 그대로 검색합니다.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.secondary,
                    )
                }
            }

            item {
                LazyRow(
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(PLACE_CATEGORIES, key = { it.kind.wire }) { category ->
                        FilterChip(
                            selected = category.kind == selectedKind,
                            enabled = !state.loading,
                            onClick = { onSearch(category.kind, state.preferParking) },
                            label = { Text(category.label) },
                        )
                    }
                }
            }

            item {
                Row(
                    modifier = Modifier.padding(horizontal = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    if (selectedKind.supportsParkingPreference()) {
                        FilterChip(
                            selected = state.preferParking,
                            enabled = !state.loading,
                            onClick = { onSearch(selectedKind, !state.preferParking) },
                            label = { Text("주차 가능 우선") },
                        )
                    }
                    Text(
                        group?.let(::sortLabel) ?: "가까운 순",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.secondary,
                    )
                }
            }

            if (selectedKind == PlaceKind.SHOPPING) {
                item {
                    Text(
                        "일반 쇼핑은 원천 데이터에 주차·입장 조건 같은 상세 사실이 대부분 없습니다.",
                        modifier = Modifier.padding(horizontal = 16.dp),
                        style = MaterialTheme.typography.bodySmall,
                        color = Color(0xFF8A5A00),
                    )
                }
            }

            group?.sort?.coverage?.get("parking")?.let { coverage ->
                item { ParkingCoverage(coverage) }
            }

            group?.let(::dogAccessCoverage)?.let { coverage ->
                item {
                    Text(
                        "입장 평가 · 가능 ${coverage.compatible} · 불일치 ${coverage.incompatible} · " +
                            "미상 ${coverage.unknown}",
                        modifier = Modifier.padding(horizontal = 16.dp),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.secondary,
                    )
                }
            }

            state.error?.let { error ->
                item {
                    Surface(
                        modifier = Modifier.padding(horizontal = 16.dp),
                        color = MaterialTheme.colorScheme.errorContainer,
                        shape = RoundedCornerShape(12.dp),
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(start = 12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(error, modifier = Modifier.weight(1f), maxLines = 2)
                            TextButton(onClick = onRetry) { Text("다시 시도") }
                        }
                    }
                }
            }

            if (state.loading) {
                item {
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(18.dp),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        CircularProgressIndicator(modifier = Modifier.width(22.dp), strokeWidth = 2.dp)
                        Spacer(Modifier.width(10.dp))
                        Text("${categoryLabel(selectedKind)} 찾는 중")
                    }
                }
            } else if (group == null && state.requestedKinds.isEmpty()) {
                item {
                    Text(
                        "현재 위치를 확인하면 주변 ${categoryLabel(selectedKind)}를 보여드릴게요.",
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                    )
                }
            } else if (group == null || group.results.isEmpty()) {
                item {
                    Text(
                        "이 반경에서 ${categoryLabel(selectedKind)} 결과를 찾지 못했습니다.",
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                    )
                }
            } else {
                item {
                    Text(
                        "${group.results.size}곳${if (group.truncated) " · 서버 한도에서 잘림" else ""}",
                        modifier = Modifier.padding(horizontal = 16.dp),
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
                item {
                    LazyRow(
                        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp),
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        items(group.results, key = { placeMarkerId(it.place.key) }) { hit ->
                            PlaceCard(
                                hit = hit,
                                selected = hit.place.key == state.selectedPlaceKey,
                                onSelect = { onSelect(hit.place.key) },
                                onCall = onCall,
                            )
                        }
                    }
                }
            }

            item { Spacer(Modifier.height(8.dp)) }
        }
    }
}

@Composable
private fun ParkingCoverage(coverage: BooleanFactCoverage) {
    Text(
        "반환 결과 주차 정보 · 가능 ${coverage.knownTrue} · 불가 ${coverage.knownFalse} · " +
            "미상 ${coverage.unknown}",
        modifier = Modifier.padding(horizontal = 16.dp),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.secondary,
    )
}

@Composable
private fun PlaceCard(
    hit: PlaceSearchHit,
    selected: Boolean,
    onSelect: () -> Unit,
    onCall: (String) -> Unit,
) {
    val place = hit.place
    val border = if (selected) MaterialTheme.colorScheme.primary else Color(0xFFDDE3DF)
    Surface(
        modifier = Modifier.width(292.dp).border(1.dp, border, RoundedCornerShape(16.dp))
            .clickable(onClick = onSelect),
        shape = RoundedCornerShape(16.dp),
        color = Color.White,
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Text(place.name, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                "${categoryLabel(place.match.kind)} · ${formatPlaceMeters(place.distanceMeters)}",
                color = MaterialTheme.colorScheme.secondary,
            )
            Text(
                parkingLabel(place.facts.parking),
                color = if (place.facts.parking == null) Color(0xFF8A5A00) else MaterialTheme.colorScheme.secondary,
            )
            hit.evaluations.dogAccess?.let { evaluation ->
                Text(
                    "${dogAccessLabel(evaluation.state)} · ${dogAccessReasonLabel(evaluation.reason)}",
                    color = dogAccessColor(evaluation.state),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            place.facts.medical?.let { medical ->
                Text(openNowLabel(medical.openNow), style = MaterialTheme.typography.bodySmall)
            }
            place.facts.hoursText?.let { hours ->
                Text("영업시간 $hours", style = MaterialTheme.typography.bodySmall, maxLines = 2)
            }
            place.facts.address?.let { address ->
                Text(address, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            place.facts.phone?.let { phone ->
                OutlinedButton(onClick = { onCall(phone) }, modifier = Modifier.fillMaxWidth()) {
                    Text("전화 $phone", maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        }
    }
}

fun categoryLabel(kind: PlaceKind): String =
    PLACE_CATEGORIES.first { it.kind == kind }.label

fun parkingLabel(value: Boolean?): String = when (value) {
    true -> "주차 가능"
    false -> "주차 불가"
    null -> "주차 정보 없음"
}

fun dogAccessLabel(state: DogAccessState): String = when (state) {
    DogAccessState.COMPATIBLE -> "입장 조건상 가능"
    DogAccessState.INCOMPATIBLE -> "조건 불일치"
    DogAccessState.UNKNOWN -> "정보 부족 · 확인 필요"
}

fun dogAccessReasonLabel(reason: String): String = when (reason) {
    "size_allowed" -> "크기 등급 허용"
    "size_exceeded" -> "크기 등급 초과"
    "weight_allowed" -> "무게 제한 허용"
    "weight_exceeded" -> "무게 제한 초과"
    "weight_boundary_unknown" -> "미만·이하 경계 확인 필요"
    "dog_disallowed" -> "개 입장 불가"
    "missing_dog_size" -> "개 크기 미상"
    "missing_dog_weight" -> "개 무게 미상"
    "missing_restriction" -> "시설 제한 정보 없음"
    else -> reason
}

fun dogAccessCoverage(group: PlaceSearchGroup): DogAccessCoverage? {
    val evaluations = group.results.mapNotNull { it.evaluations.dogAccess }
    if (evaluations.isEmpty()) return null
    return DogAccessCoverage(
        compatible = evaluations.count { it.state == DogAccessState.COMPATIBLE },
        incompatible = evaluations.count { it.state == DogAccessState.INCOMPATIBLE },
        unknown = evaluations.count { it.state == DogAccessState.UNKNOWN },
    )
}

private fun dogAccessColor(state: DogAccessState): Color = when (state) {
    DogAccessState.COMPATIBLE -> Color(0xFF226C4A)
    DogAccessState.INCOMPATIBLE -> Color(0xFF8A3333)
    DogAccessState.UNKNOWN -> Color(0xFF8A5A00)
}

private fun openNowLabel(value: Boolean?): String = when (value) {
    true -> "현재 영업 확인"
    false -> "현재 영업 종료"
    null -> "영업 여부 미상"
}

fun sortLabel(group: PlaceSearchGroup): String = when (group.sort.type) {
    PlaceSortType.DISTANCE -> "가까운 순"
    PlaceSortType.DISTANCE_PREFERRED -> {
        val band = group.sort.bandMeters
        if (band == null) "서버 지정 선호순" else "${band}m 구간 안에서 주차 가능 우선"
    }
}

private fun PlaceKind.supportsParkingPreference(): Boolean =
    this != PlaceKind.HOSPITAL && this != PlaceKind.PHARMACY

private fun formatPlaceMeters(meters: Int): String =
    if (meters >= 1_000) "%.1fkm".format(meters / 1_000.0) else "${meters}m"
