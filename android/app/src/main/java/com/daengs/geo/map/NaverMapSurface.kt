package com.daengs.geo.map

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
import com.daengs.geo.hospital.HospitalResult
import com.daengs.geo.location.GeoPoint
import com.naver.maps.geometry.LatLng
import com.naver.maps.map.CameraAnimation
import com.naver.maps.map.CameraUpdate
import com.naver.maps.map.MapView
import com.naver.maps.map.NaverMap
import com.naver.maps.map.overlay.LocationOverlay
import com.naver.maps.map.overlay.Marker
import com.naver.maps.map.overlay.OverlayImage

@Composable
fun NaverMapSurface(
    hospitals: List<HospitalResult>,
    deviceLocation: GeoPoint?,
    searchOrigin: GeoPoint?,
    selectedHospitalId: Long?,
    onCameraIdle: (GeoPoint) -> Unit,
    onSelectHospital: (Long) -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val mapView = remember { MapView(context) }
    var naverMap by remember { mutableStateOf<NaverMap?>(null) }
    val latestCameraCallback by rememberUpdatedState(onCameraIdle)

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

    DisposableEffect(naverMap, deviceLocation) {
        val overlay: LocationOverlay? = naverMap?.locationOverlay
        if (overlay != null && deviceLocation != null) {
            overlay.position = LatLng(deviceLocation.latitude, deviceLocation.longitude)
            overlay.isVisible = true
        }
        onDispose { overlay?.isVisible = false }
    }

    DisposableEffect(naverMap, hospitals, selectedHospitalId) {
        val map = naverMap
        val markers = if (map == null) emptyList() else hospitals.map { hospital ->
            Marker().apply {
                position = LatLng(hospital.point.latitude, hospital.point.longitude)
                captionText = hospital.name
                captionMinZoom = 13.0
                width = if (hospital.id == selectedHospitalId) 84 else 64
                height = if (hospital.id == selectedHospitalId) 105 else 80
                icon = OverlayImage.fromResource(
                    if (hospital.id == selectedHospitalId) {
                        com.naver.maps.map.R.drawable.navermap_default_marker_icon_green
                    } else {
                        com.naver.maps.map.R.drawable.navermap_default_marker_icon_blue
                    },
                )
                setOnClickListener {
                    onSelectHospital(hospital.id)
                    true
                }
                this.map = map
            }
        }
        onDispose { markers.forEach { it.map = null } }
    }
}
