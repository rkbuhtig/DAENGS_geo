package com.daengs.geo.place

fun interface PlaceSearchRepository {
    suspend fun search(request: PlaceSearchRequest): PlaceSearchResponse
}

class PlaceRepository(private val api: PlaceApi) : PlaceSearchRepository {
    override suspend fun search(request: PlaceSearchRequest): PlaceSearchResponse =
        api.search(request)
}
