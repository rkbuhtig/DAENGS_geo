package com.daengs.geo.journey

fun interface JourneyRepository {
    suspend fun load(request: PlaceJourneyRequest): JourneyResponse
}

class HttpJourneyRepository(private val api: JourneyApi) : JourneyRepository {
    override suspend fun load(request: PlaceJourneyRequest): JourneyResponse = api.load(request)
}
