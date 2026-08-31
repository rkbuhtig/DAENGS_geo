package com.daengs.geo.location

import android.annotation.SuppressLint
import android.content.Context
import android.location.Location
import android.os.Build
import android.os.Looper
import androidx.core.location.LocationCompat
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.google.android.gms.tasks.CancellationTokenSource
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.suspendCancellableCoroutine

class FusedLocationSource(context: Context) : LocationSource {
    private val client = LocationServices.getFusedLocationProviderClient(context)

    @SuppressLint("MissingPermission")
    override suspend fun currentLocation(): LocationSample = suspendCancellableCoroutine { continuation ->
        val cancellation = CancellationTokenSource()
        client.getCurrentLocation(Priority.PRIORITY_BALANCED_POWER_ACCURACY, cancellation.token)
            .addOnSuccessListener { location ->
                if (!continuation.isActive) return@addOnSuccessListener
                if (location == null) {
                    continuation.resumeWithException(
                        IllegalStateException("현재 위치를 가져오지 못했습니다. 위치 설정을 확인해주세요."),
                    )
                } else {
                    continuation.resume(location.toSample())
                }
            }
            .addOnFailureListener { error ->
                if (continuation.isActive) continuation.resumeWithException(error)
            }
        continuation.invokeOnCancellation { cancellation.cancel() }
    }

    @SuppressLint("MissingPermission")
    override fun locationUpdates(config: LocationUpdateConfig): Flow<LocationSample> = callbackFlow {
        val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, config.intervalMillis)
            .setMinUpdateIntervalMillis(config.minIntervalMillis)
            .setMinUpdateDistanceMeters(config.minDistanceMeters)
            .build()
        val callback = object : LocationCallback() {
            override fun onLocationResult(result: LocationResult) {
                result.locations.forEach { trySend(it.toSample()) }
            }
        }
        // Not null: the callback needs a Looper to be delivered on, and GMS rejects a null one
        // with "invalid null looper" unless the *calling thread* has its own. This flow is
        // collected from the walk service's Dispatchers.Default scope, which has none — so the
        // subscription failed instantly and every walk paused itself with zero fixes.
        client.requestLocationUpdates(request, callback, Looper.getMainLooper())
            .addOnFailureListener { close(it) }
        awaitClose { client.removeLocationUpdates(callback) }
    }
}

private fun Location.toSample(): LocationSample = LocationSample(
    point = GeoPoint(latitude = latitude, longitude = longitude),
    capturedAtMillis = time,
    elapsedRealtimeNanos = elapsedRealtimeNanos,
    accuracyMeters = accuracy.takeIf { hasAccuracy() },
    speedMetersPerSecond = speed.takeIf { hasSpeed() },
    // AVD의 `adb emu geo fix`는 실제로 만든 위치인데도 LocationCompat.isMock=false로
    // 전달된다. 그 값만 믿으면 검증 산책이 device evidence로 업로드된다. 플랫폼 표식과
    // 실행 환경을 함께 보되, 실제 Pixel의 google brand 자체는 mock 근거로 쓰지 않는다.
    isMock = isMockEvidence(
        platformReportedMock = LocationCompat.isMock(this),
        fingerprint = Build.FINGERPRINT,
        model = Build.MODEL,
        manufacturer = Build.MANUFACTURER,
        device = Build.DEVICE,
        product = Build.PRODUCT,
    ),
)

internal fun isMockEvidence(
    platformReportedMock: Boolean,
    fingerprint: String,
    model: String,
    manufacturer: String,
    device: String,
    product: String,
): Boolean = platformReportedMock ||
    fingerprint.startsWith("generic", ignoreCase = true) ||
    model.contains("emulator", ignoreCase = true) ||
    model.startsWith("sdk_", ignoreCase = true) ||
    manufacturer.contains("genymotion", ignoreCase = true) ||
    device.startsWith("emu", ignoreCase = true) ||
    product.startsWith("sdk_", ignoreCase = true)
