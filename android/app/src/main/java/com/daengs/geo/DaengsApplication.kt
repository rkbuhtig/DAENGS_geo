package com.daengs.geo

import android.app.Application
import com.daengs.geo.hospital.HospitalApi
import com.daengs.geo.hospital.HospitalRepository
import com.daengs.geo.location.FusedLocationSource
import com.daengs.geo.location.LocationSource
import com.daengs.geo.territory.InMemoryTerritoryRepository
import com.daengs.geo.territory.LocalHexCellIndexer
import com.daengs.geo.territory.TerritoryRepository
import com.daengs.geo.walk.ForegroundWalkTrackingController
import com.daengs.geo.walk.WalkFixWriter
import com.daengs.geo.walk.WalkTrackingController
import com.daengs.geo.walk.WalkTrackingStore
import com.daengs.geo.walk.HttpWalkApi
import com.daengs.geo.walk.WalkUploader
import com.daengs.geo.walk.store.DaengsDatabase
import com.daengs.geo.walk.store.RoomWalkFixLog
import com.naver.maps.map.NaverMapSdk
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

class DaengsApplication : Application() {
    lateinit var graph: AppGraph
        private set

    override fun onCreate() {
        super.onCreate()
        if (BuildConfig.NAVER_MAP_NCP_KEY_ID.isNotBlank()) {
            NaverMapSdk.getInstance(this).client =
                NaverMapSdk.NcpKeyClient(BuildConfig.NAVER_MAP_NCP_KEY_ID)
        }
        val territoryRepository = InMemoryTerritoryRepository(LocalHexCellIndexer())
        val walkTrackingStore = WalkTrackingStore()
        // Application-scoped on purpose: walk writes must outlive the service that queues them.
        val walkFixLog = RoomWalkFixLog(DaengsDatabase.open(this).walkDao())
        val walkFixWriter = WalkFixWriter(
            log = walkFixLog,
            scope = CoroutineScope(SupervisorJob() + Dispatchers.IO),
        )
        graph = AppGraph(
            hospitalRepository = HospitalRepository(HospitalApi(BuildConfig.API_BASE_URL)),
            locationSource = FusedLocationSource(this),
            territoryRepository = territoryRepository,
            walkTrackingStore = walkTrackingStore,
            walkTrackingController = ForegroundWalkTrackingController(this, walkTrackingStore),
            walkFixWriter = walkFixWriter,
            walkUploader = WalkUploader(
                api = HttpWalkApi(BuildConfig.API_BASE_URL),
                log = walkFixLog,
                dogId = BuildConfig.DEV_DOG_ID,
            ),
            dogId = BuildConfig.DEV_DOG_ID,
        )
    }
}

data class AppGraph(
    val hospitalRepository: HospitalRepository,
    val locationSource: LocationSource,
    val territoryRepository: TerritoryRepository,
    val walkTrackingStore: WalkTrackingStore,
    val walkTrackingController: WalkTrackingController,
    val walkFixWriter: WalkFixWriter,
    val walkUploader: WalkUploader,
    /** Blank until a real dog profile is wired in (decision #4). Blank disables upload. */
    val dogId: String,
)
