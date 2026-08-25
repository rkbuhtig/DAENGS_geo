package com.daengs.geo

import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * 서버 주소가 **빌드가 아니라 실행 중에** 정해지는지. 터널 주소가 바뀔 때 APK 를 다시 만들지
 * 않아도 되는 근거가 여기다.
 *
 * 기본 `Application` 으로 고정하는 이유는 `WalkDaoTest` 와 같다 — 실제 Application 은 키가
 * 있으면 NAVER SDK 를 초기화하고 그건 Robolectric 에서 죽는다.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class ServerAddressTest {

    private val context get() = ApplicationProvider.getApplicationContext<android.content.Context>()

    @Before
    fun reset() {
        ServerAddress.set(context, "")
    }

    @Test
    fun `falls back to the build value when nothing was set`() {
        assertEquals(BuildConfig.API_BASE_URL, ServerAddress.current(context))
        assertFalse(ServerAddress.isCustom(context))
    }

    @Test
    fun `a saved address wins over the build value`() {
        ServerAddress.set(context, "https://tunnel-of-the-day.example")

        assertEquals("https://tunnel-of-the-day.example", ServerAddress.current(context))
        assertTrue(ServerAddress.isCustom(context))
    }

    @Test
    fun `surrounding space and a trailing slash are cleaned off`() {
        // 붙여넣기는 대개 지저분하게 들어온다. 그대로 두면 `//hospital/search` 가 된다.
        ServerAddress.set(context, "  https://tunnel.example/  ")

        assertEquals("https://tunnel.example", ServerAddress.current(context))
    }

    @Test
    fun `an empty value returns to the build default`() {
        ServerAddress.set(context, "https://tunnel.example")
        ServerAddress.set(context, "")

        assertEquals(BuildConfig.API_BASE_URL, ServerAddress.current(context))
        assertFalse(ServerAddress.isCustom(context))
    }
}
