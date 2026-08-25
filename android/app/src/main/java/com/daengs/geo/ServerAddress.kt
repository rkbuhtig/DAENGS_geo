package com.daengs.geo

import android.content.Context

/**
 * 앱이 지금 부르는 서버 주소. **빌드 시각이 아니라 실행 중에 정해진다.**
 *
 * 개발 서버는 개발 PC 안에 있어서 폰이 밖에서 부르려면 터널을 쓰는데, 그 주소가 자주 바뀐다
 * (quick 터널은 실행할 때마다 새 주소다). 주소가 `BuildConfig` 에만 있으면 바뀔 때마다 APK 를
 * 다시 만들어야 하고, 그 사이 앱은 그냥 죽어 있다. 주소를 화면에서 고칠 수 있으면 그 고리가
 * 끊긴다.
 *
 * 저장된 값이 없으면 빌드에 박힌 값을 쓴다 — 처음 설치했을 때 아무것도 안 해도 되게.
 */
object ServerAddress {

    private const val PREFS = "daengs.dev"
    private const val KEY = "server_base_url"

    fun current(context: Context): String =
        prefs(context).getString(KEY, null)?.takeIf { it.isNotBlank() } ?: BuildConfig.API_BASE_URL

    /** 빈 값을 주면 빌드 기본값으로 되돌린다. */
    fun set(context: Context, url: String) {
        val cleaned = url.trim().trimEnd('/')
        prefs(context).edit().apply {
            if (cleaned.isBlank()) remove(KEY) else putString(KEY, cleaned)
        }.apply()
    }

    fun isCustom(context: Context): Boolean = prefs(context).contains(KEY)

    private fun prefs(context: Context) =
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
