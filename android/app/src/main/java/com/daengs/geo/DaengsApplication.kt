package com.daengs.geo

import android.app.Application
import com.daengs.geo.hospital.HospitalApi
import com.daengs.geo.hospital.HospitalRepository
import com.daengs.geo.location.FusedLocationSource
import com.daengs.geo.location.LocationSource
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
        graph = AppGraph(
            hospitalRepository = HospitalRepository(HospitalApi(BuildConfig.API_BASE_URL)),
            locationSource = FusedLocationSource(this),
        )
    }
}

data class AppGraph(
    val hospitalRepository: HospitalRepository,
    val locationSource: LocationSource,
)
