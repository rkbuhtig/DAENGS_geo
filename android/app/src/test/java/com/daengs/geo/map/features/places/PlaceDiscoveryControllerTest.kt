package com.daengs.geo.map.features.places

import com.daengs.geo.location.GeoPoint
import com.daengs.geo.place.AppliedPlaceSearchConditions
import com.daengs.geo.place.PlaceKind
import com.daengs.geo.place.PlaceSearchRequest
import com.daengs.geo.place.PlaceSearchResponse
import com.daengs.geo.place.PlaceSearchRepository
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PlaceDiscoveryControllerTest {
    @Test
    fun `an older response cannot replace a newer category search`() = runTest {
        val first = CompletableDeferred<PlaceSearchResponse>()
        val second = CompletableDeferred<PlaceSearchResponse>()
        var calls = 0
        val repository = PlaceSearchRepository { _: PlaceSearchRequest ->
            calls++
            if (calls == 1) first.await() else second.await()
        }
        val controller = PlaceDiscoveryController(repository, dogId = "", scope = this)
        val oldResponse = response("old")
        val newResponse = response("new")

        controller.search(GeoPoint(37.5, 127.0), listOf(PlaceKind.CAFE))
        runCurrent()
        controller.search(GeoPoint(37.6, 127.1), listOf(PlaceKind.HOSPITAL))
        runCurrent()

        second.complete(newResponse)
        runCurrent()
        first.complete(oldResponse)
        advanceUntilIdle()

        assertEquals(listOf(PlaceKind.HOSPITAL), controller.state.value.requestedKinds)
        assertEquals(GeoPoint(37.6, 127.1), controller.state.value.origin)
        assertSame(newResponse, controller.state.value.response)
    }

    private fun response(id: String) = PlaceSearchResponse(
        conditions = AppliedPlaceSearchConditions(
            dogId = id,
            dogSize = null,
            dogWeightKg = null,
        ),
        groups = emptyList(),
    )
}
