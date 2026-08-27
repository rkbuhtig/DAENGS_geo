package com.daengs.geo.journey

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MapHandoffTest {
    @Test
    fun `only NAVER route links with supported modes cross the Intent boundary`() {
        assertTrue(isTrustedNaverHandoff("nmap://route/walk?dlat=37.5&dlng=127.0"))
        assertTrue(isTrustedNaverHandoff("nmap://route/public?dlat=37.5&dlng=127.0"))
        assertFalse(isTrustedNaverHandoff("https://example.test/steal"))
        assertFalse(isTrustedNaverHandoff("nmap://place?lat=37.5&lng=127.0"))
        assertFalse(isTrustedNaverHandoff("nmap://route/teleport?dlat=37.5&dlng=127.0"))
    }
}
