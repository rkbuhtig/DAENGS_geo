package com.daengs.geo

import android.app.Application
import com.daengs.geo.journey.HttpJourneyRepository
import com.daengs.geo.journey.JourneyApi
import com.daengs.geo.location.FusedLocationSource
import com.daengs.geo.location.LocationSource
import com.daengs.geo.place.DogSearchContext
import com.daengs.geo.place.DogSize
import com.daengs.geo.place.PlaceApi
import com.daengs.geo.place.PlaceRepository
import com.daengs.geo.territory.InMemoryTerritoryRepository
import com.daengs.geo.territory.LocalHexCellIndexer
import com.daengs.geo.territory.TerritoryRepository
import com.daengs.geo.walk.ForegroundWalkTrackingController
import com.daengs.geo.walk.WalkFixLog
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
import java.time.LocalDate
import java.time.temporal.ChronoUnit
import kotlin.math.roundToInt

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
            placeRepository = PlaceRepository(PlaceApi(baseUrl = { ServerAddress.current(this) })),
            journeyRepository = HttpJourneyRepository(
                JourneyApi(baseUrl = { ServerAddress.current(this) }),
            ),
            locationSource = FusedLocationSource(this),
            territoryRepository = territoryRepository,
            walkTrackingStore = walkTrackingStore,
            walkTrackingController = ForegroundWalkTrackingController(this, walkTrackingStore),
            walkFixWriter = walkFixWriter,
            walkFixLog = walkFixLog,
            walkUploader = WalkUploader(
                apiFactory = { HttpWalkApi(ServerAddress.current(this)) },
                log = walkFixLog,
                dogId = BuildConfig.DEV_DOG_ID,
            ),
            dogId = BuildConfig.DEV_DOG_ID,
            dogContext = devDogContext(BuildConfig.DEV_DOG_ID),
        )
    }
}

/**
 * DEV_DOG_ID 페르소나의 **값** projection — place 검색은 identity 를 받지 않으므로
 * (결정 #73) 하네스가 프로필 소유자 역할을 대신한다. 값 출처는 서버 페르소나
 * (app/profile/source.py)이고, 나이는 서버 프로필이 하던 대로 출생일에서 계산한다.
 * 실제 프로필 연동(결정 #4)이 들어오면 이 표는 그 projection 으로 대체된다.
 */
private fun devDogContext(dogId: String): DogSearchContext? {
    val (size, weightKg, birth) = when (dogId) {
        "kong" -> Triple(DogSize.MEDIUM, 18.0, LocalDate.of(2024, 5, 1))
        "dubu" -> Triple(DogSize.SMALL, 9.0, LocalDate.of(2021, 3, 15))
        "halmae" -> Triple(DogSize.SMALL, 3.2, LocalDate.of(2013, 7, 1))
        "bau" -> Triple(DogSize.LARGE, 32.0, LocalDate.of(2022, 6, 10))
        "bbogeul" -> Triple(DogSize.SMALL, 2.1, LocalDate.of(2024, 3, 20))
        "choco" -> Triple(DogSize.SMALL, 7.5, LocalDate.of(2017, 4, 5))
        "samwol" -> Triple(DogSize.SMALL, 1.8, LocalDate.of(2026, 5, 10))
        "janggun" -> Triple(DogSize.LARGE, 34.0, LocalDate.of(2015, 2, 14))
        else -> return null
    }
    val ageYears = ChronoUnit.DAYS.between(birth, LocalDate.now()) / 365.25
    return DogSearchContext(
        size = size,
        weightKg = weightKg,
        ageYears = (ageYears * 10).roundToInt() / 10.0,
    )
}

data class AppGraph(
    /** Product place entry point shared by every category, including hospital. */
    val placeRepository: PlaceRepository,
    /** Shared selected-Place movement boundary; route following stays in the provider app. */
    val journeyRepository: HttpJourneyRepository,
    val locationSource: LocationSource,
    val territoryRepository: TerritoryRepository,
    val walkTrackingStore: WalkTrackingStore,
    val walkTrackingController: WalkTrackingController,
    val walkFixWriter: WalkFixWriter,
    /** Read side of the same Room log the writer feeds — exporter and uploader share it. */
    val walkFixLog: WalkFixLog,
    val walkUploader: WalkUploader,
    /** Blank until a real dog profile is wired in (decision #4). Blank disables upload. */
    val dogId: String,
    /** Place 검색용 값 projection. null 이면 개 조건 없이 검색한다 (결정 #73). */
    val dogContext: DogSearchContext?,
)
