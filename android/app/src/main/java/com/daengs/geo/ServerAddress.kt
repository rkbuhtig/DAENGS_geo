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

    /**
     * **release 는 저장값을 보지 않는다.** 이 기능은 개발 터널 주소가 자주 바뀌는 문제를
     * 푸는 것이고, 출고된 앱이 임의의 서버를 보는 상태는 존재할 이유가 없다. UI 가 debug
     * 전용이라 실제로 값이 생길 일은 없지만, 그 사실에 기대지 않고 여기서 닫는다.
     */
    fun current(context: Context): String {
        if (!BuildConfig.DEBUG) return BuildConfig.API_BASE_URL
        return prefs(context).getString(KEY, null)?.takeIf { it.isNotBlank() }
            ?: BuildConfig.API_BASE_URL
    }

    /**
     * 저장 결과. 실패는 값을 안 바꾼다 — "저장했다" 고 해놓고 요청할 때 터지면 원인을 엉뚱한
     * 데서 찾게 된다.
     */
    sealed interface Result {
        data object Saved : Result
        data object Cleared : Result
        data class Rejected(val reason: String) : Result
    }

    /** 빈 값을 주면 빌드 기본값으로 되돌린다. */
    fun set(context: Context, url: String): Result {
        val cleaned = url.trim().trimEnd('/')
        if (cleaned.isBlank()) {
            prefs(context).edit().remove(KEY).apply()
            return Result.Cleared
        }
        validate(cleaned)?.let { return Result.Rejected(it) }
        prefs(context).edit().putString(KEY, cleaned).apply()
        return Result.Saved
    }

    /**
     * 개발용이라 엄밀한 검증은 안 한다. 실제로 저장되는 오타만 막는다 — 저장은 성공했다고
     * 나오고 요청할 때 `URL()` 이 터지는 것이 제일 헷갈린다.
     *
     * `http` 를 막지 않는 이유: debug 매니페스트가 평문을 허용하고, `adb reverse` 로 붙는
     * `http://127.0.0.1:8000` 이 정상적인 개발 경로다.
     */
    private fun validate(url: String): String? {
        val scheme = url.substringBefore("://", missingDelimiterValue = "")
        if (scheme != "http" && scheme != "https") return "http:// 또는 https:// 로 시작해야 해요"
        val host = url.substringAfter("://").substringBefore('/').substringBefore(':')
        if (host.isBlank()) return "주소에 호스트가 없어요"
        return null
    }

    fun isCustom(context: Context): Boolean = BuildConfig.DEBUG && prefs(context).contains(KEY)

    private fun prefs(context: Context) =
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
