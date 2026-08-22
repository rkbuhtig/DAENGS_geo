package com.daengs.geo.map.shell

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.daengs.geo.location.GeoPoint
import com.daengs.geo.map.provider.naver.NaverMapSurface

@Composable
fun MapHost(
    scene: MapScene,
    searchOrigin: GeoPoint?,
    followDevice: Boolean,
    onCameraIdle: (GeoPoint) -> Unit,
    onCameraGesture: () -> Unit,
    onSelectPlace: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    NaverMapSurface(
        scene = scene,
        searchOrigin = searchOrigin,
        followDevice = followDevice,
        onCameraIdle = onCameraIdle,
        onCameraGesture = onCameraGesture,
        onSelectPlace = onSelectPlace,
        modifier = modifier,
    )
}
