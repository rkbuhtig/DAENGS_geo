package com.daengs.geo.map.provider.naver

import android.graphics.Color
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.daengs.geo.location.GeoPoint
import com.daengs.geo.map.shell.BaseMapStyle
import com.daengs.geo.map.shell.MapScene
import com.naver.maps.geometry.LatLng
import com.naver.maps.geometry.LatLngBounds
import com.naver.maps.map.CameraAnimation
import com.naver.maps.map.CameraUpdate
import com.naver.maps.map.MapView
import com.naver.maps.map.NaverMap
import com.naver.maps.map.overlay.LocationOverlay
import com.naver.maps.map.overlay.Marker
import com.naver.maps.map.overlay.OverlayImage
import com.naver.maps.map.overlay.PolygonOverlay
import com.naver.maps.map.overlay.PolylineOverlay

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

    AndroidView(
        factory = {
            mapView.apply {
                getMapAsync { map ->
                    naverMap = map
                    map.uiSettings.isLocationButtonEnabled = false
                    map.uiSettings.isZoomControlEnabled = false
                    // Nothing in this app is answered by a view wider than a city: search caps at
                    // a 10km radius and a walk is a few km. The floor also keeps marker count sane.
                    map.minZoom = MIN_ZOOM
                    map.extent = KOREA_EXTENT
                    map.addOnCameraChangeListener { reason, _ ->
                        lastCameraReason.intValue = reason
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
        modifier = modifier,
    )

    LaunchedEffect(naverMap, scene.baseMapStyle) {
        val map = naverMap ?: return@LaunchedEffect
        // App-owned Place markers were already removed by MapScenePolicy. Naver's built-in
        // symbols are background context, so keep roads/buildings readable and only lower their
        // visual weight on walk/game maps.
        map.symbolScale = symbolScaleFor(scene.baseMapStyle)
        map.setLayerGroupEnabled(NaverMap.LAYER_GROUP_BUILDING, true)
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
                // Selection is size and stacking order. Keeping the group icon means the
                // selected pin still says what kind of place it is.
                icon = OverlayImage.fromResource(place.iconGroup.marker)
                zIndex = if (place.selected) SELECTED_MARKER_Z else 0
                isHideCollidedMarkers = true
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
                PolylineOverlay().apply {
                    coords = path.map(GeoPoint::toLatLng)
                    width = 12
                    color = Color.rgb(34, 108, 74)
                    this.map = map
                }
            }
        }
        onDispose { lines.forEach { it.map = null } }
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

private fun GeoPoint.toLatLng(): LatLng = LatLng(latitude, longitude)

internal fun symbolScaleFor(style: BaseMapStyle): Float = when (style) {
    BaseMapStyle.SEARCH_DETAIL -> 1f
    BaseMapStyle.WALK_CONTEXT -> 0.85f
    BaseMapStyle.TERRITORY_FOCUSED -> 0.65f
}

/** Selected place pins draw above their neighbours so the choice stays visible when markers collide. */
private const val SELECTED_MARKER_Z = 100

/** Zoom floor. Below this the search radius cap (10km) is already off-screen and marker count spikes. */
private const val MIN_ZOOM = 11.0

/** The camera cannot leave the country the data covers — every source is domestic. */
private val KOREA_EXTENT = LatLngBounds(LatLng(32.9, 124.0), LatLng(38.7, 132.0))
