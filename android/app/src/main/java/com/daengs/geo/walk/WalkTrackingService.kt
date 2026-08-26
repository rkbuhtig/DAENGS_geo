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
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import com.daengs.geo.BuildConfig
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
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.launch
import kotlin.coroutines.cancellation.CancellationException
import java.util.UUID

/**
 * Owns the user-started walk recording lifecycle independently from any Activity/ViewModel.
 *
 * Collection only: scoring, WalkFacts and upload do not live here. What the device reports is
 * written to [WalkFixLog] as it arrives — raw, before TrailRecorder filtering — so a walk survives
 * process death. A session left without a close is the recovery signal, not a bug.
 */
class WalkTrackingService : Service() {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val recorder = TrailRecorder()

    private lateinit var locationSource: LocationSource
    private lateinit var tracker: LocationTracker
    private lateinit var store: WalkTrackingStore
    private lateinit var writer: WalkFixWriter
    private lateinit var uploader: WalkUploader
    private lateinit var exporter: WalkSessionExporter
    private lateinit var dogId: String

    /** Non-null exactly while a walk owns a stored session. Late fixes after stop are dropped. */
    private val sessionLock = Any()
    private var sessionId: String? = null
    private var nextClientSeq = 0
    private var chainIndex = 0

    override fun onCreate() {
        super.onCreate()
        val graph = (application as DaengsApplication).graph
        locationSource = graph.locationSource
        store = graph.walkTrackingStore
        writer = graph.walkFixWriter
        uploader = graph.walkUploader
        exporter = WalkSessionExporter(
            log = graph.walkFixLog,
            directory = java.io.File(filesDir, WalkSessionExporter.DIRECTORY),
        )
        dogId = graph.dogId
        tracker = LocationTracker(serviceScope)
        createNotificationChannel()

        serviceScope.launch {
            tracker.updates.collect(::acceptLocation)
        }
        serviceScope.launch {
            tracker.status.collect(::acceptFeedStatus)
        }
        serviceScope.launch {
            writer.failure.filterNotNull().collect(::acceptStorageFailure)
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
        // Without an approved recovery policy we must not invent a restarted walk after process death.
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
        writer.clearFailure()
        val trail = recorder.start()
        openSession()
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
        synchronized(sessionLock) { chainIndex += 1 }
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
        if (recorder.snapshot().state == TrackingState.OFF) return
        tracker.stop()
        val finishedId = closeSession()
        val trail = recorder.stop()
        store.publish(
            WalkTrackingState(
                trail = trail,
                lastSample = store.state.value.lastSample,
            ),
        )
        serviceScope.launch {
            try {
                // closeSession was submitted after every accepted fix under sessionLock.
                writer.flush()
                // Export before upload: if the upload path crashes, the file already exists —
                // it is the handoff copy of the only surviving trajectory (server purges at finish).
                exportQuietly(finishedId)
                uploadQuietly(finishedId)
            } finally {
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
    }

    private fun acceptLocation(sample: LocationSample) {
        // Stored before the recorder sees it. The recorder drops jitter and bad accuracy to draw a
        // clean line; those thresholds are provisional, and a dropped fix cannot be recovered.
        synchronized(sessionLock) {
            sessionId?.let { id ->
                writer.append(
                    id,
                    RecordedFix(
                        clientSeq = nextClientSeq++,
                        chainIndex = chainIndex,
                        atMillis = sample.capturedAtMillis,
                        lat = sample.point.latitude,
                        lng = sample.point.longitude,
                        accuracyM = sample.accuracyMeters,
                        isMock = sample.isMock,
                    ),
                )
            }
        }
        val trail = recorder.add(sample)
        store.publish(
            WalkTrackingState(
                trail = trail,
                lastSample = sample,
            ),
        )
    }

    private fun openSession() {
        val id = UUID.randomUUID().toString()
        synchronized(sessionLock) {
            sessionId = id
            nextClientSeq = 0
            chainIndex = 0
            // The repo owns no dog profile (decision #4), so this is whatever the build
            // injected — a server persona in debug, blank in release. Stored with the session
            // rather than attached at upload time: the local row has to know whose walk it
            // was, or `dog_id` cannot select this walk for deletion either.
            writer.openSession(
                RecordedSession(id = id, dogId = dogId.ifBlank { null }, startedAtMillis = now()),
            )
        }
    }

    /** Only an explicit stop closes a session. Process death deliberately leaves it open. */
    private fun closeSession(): String? = synchronized(sessionLock) {
        val closing = sessionId
        closing?.let { writer.closeSession(it, now()) }
        sessionId = null
        closing
    }

    /**
     * Upload is best-effort and never blocks the walk from ending. A failure here means the
     * server has no facts yet, not that the walk was lost — the raw fixes are in Room and the
     * whole session can be resent later, because every endpoint collapses repeats.
     */
    /** Debug builds drop a JSON copy of the finished session for `scripts/verify/walk_bundle.py`. */
    private suspend fun exportQuietly(sessionId: String?) {
        if (sessionId == null || !BuildConfig.DEBUG) return
        try {
            val file = exporter.export(sessionId)
            if (file != null) Log.i(TAG, "exported $sessionId -> ${file.name}")
        } catch (cancellation: CancellationException) {
            throw cancellation
        } catch (error: Throwable) {
            Log.w(TAG, "walk export failed for $sessionId; rows stay in Room", error)
        }
    }

    private suspend fun uploadQuietly(sessionId: String?) {
        if (sessionId == null || !uploader.enabled) return
        try {
            val result = uploader.upload(sessionId)
            if (result != null) {
                Log.i(
                    TAG,
                    "uploaded $sessionId: ${result.fixCount} fixes " +
                        "(stored=${result.stored} duplicates=${result.duplicates}) " +
                        "facts=${result.facts["facts"]} encounters=${result.facts["encounters"]}",
                )
            }
        } catch (cancellation: CancellationException) {
            throw cancellation
        } catch (error: Throwable) {
            Log.w(TAG, "walk upload failed for $sessionId; rows stay in Room", error)
        }
    }

    private fun now(): Long = System.currentTimeMillis()

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

    private fun acceptStorageFailure(message: String) {
        val trail = recorder.snapshot()
        if (trail.state == TrackingState.OFF) return
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

        private const val TAG = "WalkTrackingService"

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
