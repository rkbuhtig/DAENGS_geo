package com.daengs.geo.map.provider.naver

import android.graphics.Color
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
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
import com.daengs.geo.map.shell.MapScene
import com.naver.maps.geometry.LatLng
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
                    map.addOnCameraChangeListener { reason, _ ->
                        if (reason == CameraUpdate.REASON_GESTURE) latestGestureCallback()
                    }
                    map.addOnCameraIdleListener {
                        val target = map.cameraPosition.target
                        latestCameraCallback(GeoPoint(target.latitude, target.longitude))
                    }
                }
            }
        },
        modifier = modifier,
    )

    LaunchedEffect(naverMap, searchOrigin) {
        val map = naverMap ?: return@LaunchedEffect
        val origin = searchOrigin ?: return@LaunchedEffect
        map.moveCamera(
            CameraUpdate.scrollAndZoomTo(LatLng(origin.latitude, origin.longitude), 14.5)
                .animate(CameraAnimation.Easing),
        )
    }

    LaunchedEffect(naverMap, scene.deviceLocation, followDevice) {
        val map = naverMap ?: return@LaunchedEffect
        val point = scene.deviceLocation ?: return@LaunchedEffect
        if (followDevice) {
            map.moveCamera(CameraUpdate.scrollTo(LatLng(point.latitude, point.longitude)))
        }
    }

    DisposableEffect(naverMap, scene.deviceLocation) {
        val overlay: LocationOverlay? = naverMap?.locationOverlay
        if (overlay != null && scene.deviceLocation != null) {
            overlay.position = LatLng(scene.deviceLocation.latitude, scene.deviceLocation.longitude)
            overlay.isVisible = true
        }
        onDispose { overlay?.isVisible = false }
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
        val line = if (
            map != null && scene.trail.visible && scene.trail.points.size >= 2
        ) {
            PolylineOverlay().apply {
                coords = scene.trail.points.map(GeoPoint::toLatLng)
                width = 12
                color = Color.rgb(34, 108, 74)
                this.map = map
            }
        } else {
            null
        }
        onDispose { line?.map = null }
    }

    DisposableEffect(naverMap, scene.territory) {
        val map = naverMap
        val polygons = if (map == null || !scene.territory.visible) {
            emptyList()
        } else {
            buildList {
                scene.territory.claimedCells.forEach { cell ->
                    add(
                        PolygonOverlay().apply {
                            coords = cell.boundary.map(GeoPoint::toLatLng)
                            color = Color.argb(105, 34, 108, 74)
                            outlineColor = Color.rgb(34, 108, 74)
                            outlineWidth = 3
                            this.map = map
                        },
                    )
                }
                val preview = scene.territory.previewCell
                if (preview != null && scene.territory.claimedCells.none { it.id == preview.id }) {
                    add(
                        PolygonOverlay().apply {
                            coords = preview.boundary.map(GeoPoint::toLatLng)
                            color = Color.argb(70, 255, 174, 0)
                            outlineColor = Color.rgb(214, 125, 0)
                            outlineWidth = 3
                            this.map = map
                        },
                    )
                }
            }
        }
        onDispose { polygons.forEach { it.map = null } }
    }
}

private fun GeoPoint.toLatLng(): LatLng = LatLng(latitude, longitude)
