package com.daengs.geo.map.provider.naver

import com.daengs.geo.map.shell.BaseMapStyle
import org.junit.Assert.assertEquals
import org.junit.Test

class NaverMapStylePolicyTest {
    @Test
    fun `provider keeps search context and progressively mutes symbols for activity maps`() {
        assertEquals(1f, symbolScaleFor(BaseMapStyle.SEARCH_DETAIL))
        assertEquals(0.85f, symbolScaleFor(BaseMapStyle.WALK_CONTEXT))
        assertEquals(0.65f, symbolScaleFor(BaseMapStyle.TERRITORY_FOCUSED))
    }
}
