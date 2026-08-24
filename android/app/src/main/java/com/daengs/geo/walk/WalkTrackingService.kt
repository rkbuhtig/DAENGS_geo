package com.daengs.geo.walk

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import com.daengs.geo.DaengsApplication
import com.daengs.geo.MainActivity
import com.daengs.geo.R
import com.daengs.geo.location.FeedStatus
import com.daengs.geo.location.LocationSample
import com.daengs.geo.location.LocationSource
import com.daengs.geo.location.LocationTracker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch

/**
 * Owns the user-started walk recording lifecycle independently from any Activity/ViewModel.
 *
 * This is intentionally collection-only: no Room persistence, upload, scoring or WalkFacts live
 * here yet. Those consumers can be added behind the same service-owned session boundary later.
 */
class WalkTrackingService : Service() {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val recorder = TrailRecorder()

    private lateinit var locationSource: LocationSource
    private lateinit var tracker: LocationTracker
    private lateinit var store: WalkTrackingStore

    override fun onCreate() {
        super.onCreate()
        val graph = (application as DaengsApplication).graph
        locationSource = graph.locationSource
        store = graph.walkTrackingStore
        tracker = LocationTracker(serviceScope)
        createNotificationChannel()

        serviceScope.launch {
            tracker.updates.collect(::acceptLocation)
        }
        serviceScope.launch {
            tracker.status.collect(::acceptFeedStatus)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startRecording()
            ACTION_PAUSE -> pauseRecording()
            ACTION_RESUME -> resumeRecording()
            ACTION_STOP -> stopRecording()
            else -> Unit
        }
        // Without local session persistence we must not invent a restarted walk after process death.
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        tracker.stop()
        if (recorder.snapshot().state != TrackingState.OFF) {
            val trail = recorder.pause()
            store.publish(
                WalkTrackingState(
                    trail = trail,
                    lastSample = store.state.value.lastSample,
                    errorMessage = "산책 기록 서비스가 종료되었습니다.",
                ),
            )
        }
        serviceScope.cancel()
        super.onDestroy()
    }

    private fun startRecording() {
        if (recorder.snapshot().state != TrackingState.OFF) {
            promote(recorder.snapshot(), store.state.value.errorMessage)
            return
        }
        val trail = recorder.start()
        store.publish(WalkTrackingState(trail = trail))
        // Android 14+ checks the location FGS permission at promotion time. Promote before the
        // LocationSource is collected so location access begins under the declared FGS type.
        promote(trail, errorMessage = null)
        tracker.start(locationSource)
    }

    private fun pauseRecording() {
        if (recorder.snapshot().state != TrackingState.RECORDING) return
        tracker.stop()
        val trail = recorder.pause()
        store.publish(
            WalkTrackingState(
                trail = trail,
                lastSample = store.state.value.lastSample,
            ),
        )
        promote(trail, errorMessage = null)
    }

    private fun resumeRecording() {
        if (recorder.snapshot().state != TrackingState.PAUSED) return
        val trail = recorder.resume()
        store.publish(
            WalkTrackingState(
                trail = trail,
                lastSample = store.state.value.lastSample,
            ),
        )
        promote(trail, errorMessage = null)
        tracker.start(locationSource)
    }

    private fun stopRecording() {
        tracker.stop()
        val trail = recorder.stop()
        store.publish(
            WalkTrackingState(
                trail = trail,
                lastSample = store.state.value.lastSample,
            ),
        )
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun acceptLocation(sample: LocationSample) {
        val trail = recorder.add(sample)
        store.publish(
            WalkTrackingState(
                trail = trail,
                lastSample = sample,
            ),
        )
    }

    private fun acceptFeedStatus(status: FeedStatus) {
        when (status) {
            is FeedStatus.Failed -> pauseAfterFeedProblem(status.cause.message ?: "위치를 계속 받을 수 없습니다.")
            FeedStatus.Completed -> {
                if (recorder.snapshot().state == TrackingState.RECORDING) {
                    pauseAfterFeedProblem("위치 업데이트가 종료되어 산책 기록을 일시정지했습니다.")
                }
            }
            FeedStatus.Idle, FeedStatus.Running -> Unit
        }
    }

    private fun pauseAfterFeedProblem(message: String) {
        tracker.stop()
        val trail = recorder.pause()
        store.publish(
            WalkTrackingState(
                trail = trail,
                lastSample = store.state.value.lastSample,
                errorMessage = message,
            ),
        )
        promote(trail, errorMessage = message)
    }

    private fun promote(trail: TrailSnapshot, errorMessage: String?) {
        ServiceCompat.startForeground(
            this,
            NOTIFICATION_ID,
            buildNotification(trail, errorMessage),
            ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION,
        )
    }

    private fun buildNotification(trail: TrailSnapshot, errorMessage: String?): Notification {
        val text = errorMessage ?: when (trail.state) {
            TrackingState.RECORDING -> "산책 동선을 기록하고 있어요."
            TrackingState.PAUSED -> "산책 기록이 일시정지됐어요."
            TrackingState.OFF -> "산책 기록을 마쳤어요."
        }
        val builder = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_walk_notification)
            .setContentTitle("댕스 산책 기록")
            .setContentText(text)
            .setContentIntent(openAppPendingIntent())
            .setOnlyAlertOnce(true)
            .setOngoing(trail.state != TrackingState.OFF)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)

        when (trail.state) {
            TrackingState.RECORDING -> builder.addAction(
                R.drawable.ic_walk_notification,
                "일시정지",
                servicePendingIntent(ACTION_PAUSE, REQUEST_PAUSE),
            )
            TrackingState.PAUSED -> builder.addAction(
                R.drawable.ic_walk_notification,
                "계속 기록",
                servicePendingIntent(ACTION_RESUME, REQUEST_RESUME),
            )
            TrackingState.OFF -> Unit
        }
        if (trail.state != TrackingState.OFF) {
            builder.addAction(
                R.drawable.ic_walk_notification,
                "종료",
                servicePendingIntent(ACTION_STOP, REQUEST_STOP),
            )
        }
        return builder.build()
    }

    private fun openAppPendingIntent(): PendingIntent = PendingIntent.getActivity(
        this,
        REQUEST_OPEN,
        Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
        },
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )

    private fun servicePendingIntent(action: String, requestCode: Int): PendingIntent =
        PendingIntent.getService(
            this,
            requestCode,
            commandIntent(this, action),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

    private fun createNotificationChannel() {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                "산책 기록",
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "산책 중 위치 기록 상태를 표시합니다."
            },
        )
    }

    companion object {
        const val ACTION_START = "com.daengs.geo.walk.START"
        const val ACTION_PAUSE = "com.daengs.geo.walk.PAUSE"
        const val ACTION_RESUME = "com.daengs.geo.walk.RESUME"
        const val ACTION_STOP = "com.daengs.geo.walk.STOP"

        private const val CHANNEL_ID = "walk_tracking"
        private const val NOTIFICATION_ID = 4101
        private const val REQUEST_OPEN = 4101
        private const val REQUEST_PAUSE = 4102
        private const val REQUEST_RESUME = 4103
        private const val REQUEST_STOP = 4104

        fun commandIntent(context: Context, action: String): Intent =
            Intent(context, WalkTrackingService::class.java).setAction(action)
    }
}
