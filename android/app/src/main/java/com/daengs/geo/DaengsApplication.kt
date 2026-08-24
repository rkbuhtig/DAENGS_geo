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
import com.daengs.geo.walk.WalkTrackingController
import com.daengs.geo.walk.WalkTrackingStore
import com.naver.maps.map.NaverMapSdk

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
        graph = AppGraph(
            hospitalRepository = HospitalRepository(HospitalApi(BuildConfig.API_BASE_URL)),
            locationSource = FusedLocationSource(this),
            territoryRepository = territoryRepository,
            walkTrackingStore = walkTrackingStore,
            walkTrackingController = ForegroundWalkTrackingController(this, walkTrackingStore),
        )
    }
}

data class AppGraph(
    val hospitalRepository: HospitalRepository,
    val locationSource: LocationSource,
    val territoryRepository: TerritoryRepository,
    val walkTrackingStore: WalkTrackingStore,
    val walkTrackingController: WalkTrackingController,
)
