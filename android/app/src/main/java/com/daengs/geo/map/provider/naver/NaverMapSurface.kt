package com.daengs.geo.map.provider.naver

import android.graphics.Color
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.daengs.geo.location.GeoPoint
import com.daengs.geo.map.shell.MapScene
import com.naver.maps.geometry.LatLng
import com.naver.maps.map.CameraAnimation
import com.naver.maps.map.CameraUpdate
import com.naver.maps.map.MapView
import com.naver.maps.map.NaverMap
import com.naver.maps.map.overlay.LocationOverlay
import com.naver.maps.map.overlay.Marker
import com.naver.maps.map.overlay.OverlayImage
import com.naver.maps.map.overlay.PathOverlay
import com.naver.maps.map.overlay.PolygonOverlay
import java.util.Locale
import kotlin.math.roundToInt

private const val TRAIL_WIDTH_METERS = 3.0
private const val MIN_TRAIL_WIDTH_PX = 1

@Composable
fun NaverMapSurface(
    scene: MapScene,
    searchOrigin: GeoPoint?,
    followDevice: Boolean,
    onCameraIdle: (GeoPoint) -> Unit,
    onCameraGesture: () -> Unit,
    onSelectPlace: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val mapView = remember { MapView(context) }
    var naverMap by remember { mutableStateOf<NaverMap?>(null) }
    var cameraZoom by remember { mutableDoubleStateOf(14.5) }
    var trailWidthPx by remember { mutableIntStateOf(MIN_TRAIL_WIDTH_PX) }
    val trailOverlays = remember { mutableListOf<PathOverlay>() }
    val latestCameraCallback by rememberUpdatedState(onCameraIdle)
    val latestGestureCallback by rememberUpdatedState(onCameraGesture)
    // Idle fires for our own moveCamera calls too. Without the reason, following the device
    // would look exactly like the user panning the map.
    val lastCameraReason = remember { mutableIntStateOf(CameraUpdate.REASON_DEVELOPER) }

    DisposableEffect(mapView, lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_CREATE -> mapView.onCreate(null)
                Lifecycle.Event.ON_START -> mapView.onStart()
                Lifecycle.Event.ON_RESUME -> mapView.onResume()
                Lifecycle.Event.ON_PAUSE -> mapView.onPause()
                Lifecycle.Event.ON_STOP -> mapView.onStop()
                Lifecycle.Event.ON_DESTROY -> mapView.onDestroy()
                else -> Unit
            }
        }
        lifecycle.addObserver(observer)
        onDispose {
            lifecycle.removeObserver(observer)
            mapView.onDestroy()
        }
    }

    Box(modifier = modifier) {
        AndroidView(
            factory = {
                mapView.apply {
                    getMapAsync { map ->
                        naverMap = map
                        cameraZoom = map.cameraPosition.zoom
                        trailWidthPx = trailWidthPixels(map.projection.metersPerPixel)
                        map.uiSettings.isLocationButtonEnabled = false
                        map.uiSettings.isZoomControlEnabled = true
                        map.addOnCameraChangeListener { reason, _ ->
                            lastCameraReason.intValue = reason
                            cameraZoom = map.cameraPosition.zoom
                            val nextTrailWidth = trailWidthPixels(map.projection.metersPerPixel)
                            if (nextTrailWidth != trailWidthPx) {
                                trailWidthPx = nextTrailWidth
                                trailOverlays.forEach { it.width = nextTrailWidth }
                            }
                            if (reason == CameraUpdate.REASON_GESTURE) latestGestureCallback()
                        }
                        map.addOnCameraIdleListener {
                            if (!lastCameraReason.intValue.isUserDriven()) return@addOnCameraIdleListener
                            val target = map.cameraPosition.target
                            latestCameraCallback(GeoPoint(target.latitude, target.longitude))
                        }
                    }
                }
            },
            modifier = Modifier.fillMaxSize(),
        )

        Surface(
            modifier = Modifier.align(Alignment.TopEnd).padding(12.dp),
            shape = RoundedCornerShape(12.dp),
            color = MaterialTheme.colorScheme.surface.copy(alpha = 0.9f),
            shadowElevation = 2.dp,
        ) {
            Text(
                text = String.format(Locale.US, "줌 %.1f · 선 %dpx", cameraZoom, trailWidthPx),
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                style = MaterialTheme.typography.labelLarge,
            )
        }
    }

    LaunchedEffect(naverMap, searchOrigin) {
        val map = naverMap ?: return@LaunchedEffect
        val origin = searchOrigin ?: return@LaunchedEffect
        map.moveCamera(
            CameraUpdate.scrollAndZoomTo(LatLng(origin.latitude, origin.longitude), 14.5)
                .animate(CameraAnimation.Easing),
        )
    }

    LaunchedEffect(naverMap, scene.currentPosition, followDevice) {
        val map = naverMap ?: return@LaunchedEffect
        val point = scene.currentPosition ?: return@LaunchedEffect
        if (followDevice) map.moveCamera(CameraUpdate.scrollTo(point.toLatLng()))
    }

    DisposableEffect(naverMap) {
        val overlay: LocationOverlay? = naverMap?.locationOverlay
        onDispose { overlay?.isVisible = false }
    }

    LaunchedEffect(naverMap, scene.currentPosition) {
        val overlay = naverMap?.locationOverlay ?: return@LaunchedEffect
        val point = scene.currentPosition
        if (point == null) {
            overlay.isVisible = false
        } else {
            overlay.position = point.toLatLng()
            overlay.isVisible = true
        }
    }

    DisposableEffect(naverMap, scene.places) {
        val map = naverMap
        val markers = if (map == null) emptyList() else scene.places.map { place ->
            Marker().apply {
                position = place.point.toLatLng()
                captionText = place.label
                captionMinZoom = 13.0
                width = if (place.selected) 84 else 64
                height = if (place.selected) 105 else 80
                icon = OverlayImage.fromResource(
                    if (place.selected) {
                        com.naver.maps.map.R.drawable.navermap_default_marker_icon_green
                    } else {
                        com.naver.maps.map.R.drawable.navermap_default_marker_icon_blue
                    },
                )
                setOnClickListener {
                    onSelectPlace(place.id)
                    true
                }
                this.map = map
            }
        }
        onDispose { markers.forEach { it.map = null } }
    }

    DisposableEffect(naverMap, scene.trail) {
        val map = naverMap
        val lines = if (map == null) {
            emptyList()
        } else {
            scene.trail.paths.filter { it.size >= 2 }.map { path ->
                PathOverlay().apply {
                    coords = path.map(GeoPoint::toLatLng)
                    width = trailWidthPx
                    color = Color.rgb(34, 108, 74)
                    passedColor = color
                    outlineWidth = 0
                    progress = 1.0
                    this.map = map
                }
            }
        }
        trailOverlays.addAll(lines)
        onDispose {
            lines.forEach { it.map = null }
            trailOverlays.removeAll(lines.toSet())
        }
    }

    // Claimed cells and the preview cell change on different clocks: rebuilding every claimed
    // polygon each time the walker crosses a hex would churn the whole layer.
    DisposableEffect(naverMap, scene.territory.claimedCells) {
        val map = naverMap
        val polygons = if (map == null) {
            emptyList()
        } else {
            scene.territory.claimedCells.map { cell ->
                hexPolygon(
                    cell.boundary,
                    fill = Color.argb(105, 34, 108, 74),
                    outline = Color.rgb(34, 108, 74),
                ).apply { this.map = map }
            }
        }
        onDispose { polygons.forEach { it.map = null } }
    }

    DisposableEffect(naverMap, scene.territory.previewCell, scene.territory.claimedCells) {
        val map = naverMap
        val preview = scene.territory.previewCell
        val polygon = if (
            map != null && preview != null && scene.territory.claimedCells.none { it.id == preview.id }
        ) {
            hexPolygon(
                preview.boundary,
                fill = Color.argb(70, 255, 174, 0),
                outline = Color.rgb(214, 125, 0),
            ).apply { this.map = map }
        } else {
            null
        }
        onDispose { polygon?.map = null }
    }
}

private fun hexPolygon(boundary: List<GeoPoint>, fill: Int, outline: Int) = PolygonOverlay().apply {
    coords = boundary.map(GeoPoint::toLatLng)
    color = fill
    outlineColor = outline
    outlineWidth = 3
}

private fun Int.isUserDriven(): Boolean =
    this == CameraUpdate.REASON_GESTURE || this == CameraUpdate.REASON_CONTROL

private fun trailWidthPixels(metersPerPixel: Double): Int =
    (TRAIL_WIDTH_METERS / metersPerPixel)
        .roundToInt()
        .coerceAtLeast(MIN_TRAIL_WIDTH_PX)

private fun GeoPoint.toLatLng(): LatLng = LatLng(latitude, longitude)
