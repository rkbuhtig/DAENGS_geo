package com.daengs.geo.place

class PlaceRepository(private val api: PlaceApi) {
    suspend fun search(request: PlaceSearchRequest): PlaceSearchResponse = api.search(request)
}
