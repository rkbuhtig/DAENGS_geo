package com.daengs.geo.map.features.journey

import com.daengs.geo.journey.JourneyItem
import com.daengs.geo.journey.PlaceJourneyRequest
import com.daengs.geo.location.GeoPoint
import com.daengs.geo.place.PlaceKey
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PlaceJourneyControllerTest {
    private val request = PlaceJourneyRequest(
        origin = GeoPoint(37.4979, 127.0276),
        destinationKey = PlaceKey("medical", "hospital-7"),
        destinationName = "댕스동물병원",
        destination = GeoPoint(37.5145, 127.0316),
    )

    @Test
    fun `response destination must match the requested canonical Place point`() {
        assertTrue(journeyDestinationMatches(itemAt(37.5145, 127.0316), request))
        assertFalse(journeyDestinationMatches(itemAt(35.1796, 129.0756), request))
    }

    private fun itemAt(latitude: Double, longitude: Double) = JourneyItem(
        destination = GeoPoint(latitude, longitude),
        name = "댕스동물병원",
        straightMeters = 0,
        modePriority = emptyList(),
        legs = emptyMap(),
    )
}
