package com.daengs.geo

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.core.net.toUri
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.daengs.geo.map.MapScreen
import com.daengs.geo.map.MapViewModel

class MainActivity : ComponentActivity() {
    private val viewModel: MapViewModel by viewModels {
        val graph = (application as DaengsApplication).graph
        MapViewModel.Factory(
            graph.hospitalRepository,
            graph.locationSource,
            graph.territoryRepository,
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            DaengsTheme {
                val state by viewModel.uiState.collectAsStateWithLifecycle()
                val context = LocalContext.current
                val hasLocationPermission =
                    ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) ==
                        PackageManager.PERMISSION_GRANTED
                val permissionLauncher = rememberLauncherForActivityResult(
                    ActivityResultContracts.RequestMultiplePermissions(),
                ) { grants ->
                    if (grants.values.any { it }) viewModel.locateAndSearch()
                }

                LaunchedEffect(hasLocationPermission) {
                    if (hasLocationPermission && state.deviceLocation == null && !state.loading) {
                        viewModel.locateAndSearch()
                    }
                }

                if (hasLocationPermission) {
                    MapScreen(
                        state = state,
                        mapConfigured = BuildConfig.NAVER_MAP_NCP_KEY_ID.isNotBlank(),
                        onCameraIdle = viewModel::onCameraIdle,
                        onCameraGesture = viewModel::onCameraGesture,
                        onSearchArea = viewModel::searchPinnedArea,
                        onMyLocation = viewModel::followMyLocation,
                        onAction = viewModel::execute,
                        onRetry = viewModel::retry,
                        onHundredMeters = viewModel::searchAtHundredMeters,
                        onSelectHospital = viewModel::selectHospital,
                        onCall = { phone -> dial(context = context, phone = phone) },
                        onStartTracking = viewModel::startTracking,
                        onPauseTracking = viewModel::pauseTracking,
                        onResumeTracking = viewModel::resumeTracking,
                        onStopTracking = viewModel::stopTracking,
                        onToggleTrail = viewModel::toggleTrail,
                        onToggleTerritory = viewModel::toggleTerritory,
                        onClaimTerritory = viewModel::claimCurrentCell,
                        onStartReplay = viewModel::startReplay,
                        onUseDeviceLocation = viewModel::useDeviceLocation,
                    )
                } else {
                    LocationPermissionScreen(
                        onRequest = {
                            permissionLauncher.launch(
                                arrayOf(
                                    Manifest.permission.ACCESS_COARSE_LOCATION,
                                    Manifest.permission.ACCESS_FINE_LOCATION,
                                ),
                            )
                        },
                    )
                }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        viewModel.onAppForeground()
    }

    override fun onStop() {
        viewModel.onAppBackground()
        super.onStop()
    }
}

private fun dial(context: android.content.Context, phone: String) {
    val safe = phone.filter { it.isDigit() || it in "+*#," }
    if (safe.isNotBlank()) context.startActivity(Intent(Intent.ACTION_DIAL, "tel:$safe".toUri()))
}

@Composable
private fun LocationPermissionScreen(onRequest: () -> Unit) {
    Box(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        contentAlignment = Alignment.Center,
    ) {
        Surface(shape = RoundedCornerShape(24.dp), tonalElevation = 4.dp) {
            Column(modifier = Modifier.padding(24.dp)) {
                Text("내 주변 병원을 지도에서 찾아볼게요", style = MaterialTheme.typography.headlineSmall)
                Spacer(Modifier.height(12.dp))
                Text("앱을 사용하는 동안의 위치만 요청합니다. 산책을 시작하기 전에는 백그라운드 위치를 사용하지 않아요.")
                Spacer(Modifier.height(20.dp))
                Button(onClick = onRequest, modifier = Modifier.fillMaxWidth()) {
                    Text("내 위치로 시작")
                }
            }
        }
    }
}

@Composable
private fun DaengsTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = lightColorScheme(
            primary = Color(0xFF226C4A),
            secondary = Color(0xFF4F6357),
            background = Color(0xFFF8FAF7),
            surface = Color(0xFFF8FAF7),
        ),
        content = content,
    )
}
