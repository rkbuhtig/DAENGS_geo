package com.daengs.geo.location

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FusedLocationSourceTest {

    @Test
    fun `platform mock flag always wins`() {
        assertTrue(isMockEvidence(true, "google/device", "Pixel 8", "Google", "shiba", "shiba"))
    }

    @Test
    fun `Android Studio AVD is mock even when fused location omits the flag`() {
        assertTrue(isMockEvidence(
            platformReportedMock = false,
            fingerprint = "google/sdk_gphone16k_x86_64/emu64xa16k:17/dev-keys",
            model = "sdk_gphone16k_x86_64",
            manufacturer = "Google",
            device = "emu64xa16k",
            product = "sdk_gphone16k_x86_64",
        ))
    }

    @Test
    fun `a physical Google Pixel is not mock just because of its brand`() {
        assertFalse(isMockEvidence(
            platformReportedMock = false,
            fingerprint = "google/shiba/shiba:16/release-keys",
            model = "Pixel 8",
            manufacturer = "Google",
            device = "shiba",
            product = "shiba",
        ))
    }
}
