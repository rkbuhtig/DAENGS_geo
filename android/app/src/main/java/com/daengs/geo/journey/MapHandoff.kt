package com.daengs.geo.journey

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.widget.Toast
import androidx.core.net.toUri
import java.net.URI

private const val NAVER_MAP_PACKAGE = "com.nhn.android.nmap"

/** Only the server-owned NAVER route scheme may cross into an external Intent. */
fun isTrustedNaverHandoff(url: String): Boolean {
    val uri = runCatching { URI.create(url) }.getOrNull() ?: return false
    return uri.scheme == "nmap" && uri.host == "route" && uri.path.trimStart('/').substringBefore('/') in
        setOf("walk", "car", "public")
}

fun openNaverHandoff(context: Context, url: String) {
    if (!isTrustedNaverHandoff(url)) {
        Toast.makeText(context, "지원하지 않는 길찾기 링크입니다.", Toast.LENGTH_SHORT).show()
        return
    }
    try {
        context.startActivity(Intent(Intent.ACTION_VIEW, url.toUri()).setPackage(NAVER_MAP_PACKAGE))
    } catch (_: ActivityNotFoundException) {
        val market = Intent(
            Intent.ACTION_VIEW,
            "market://details?id=$NAVER_MAP_PACKAGE".toUri(),
        )
        runCatching { context.startActivity(market) }.onFailure {
            context.startActivity(
                Intent(
                    Intent.ACTION_VIEW,
                    "https://play.google.com/store/apps/details?id=$NAVER_MAP_PACKAGE".toUri(),
                ),
            )
        }
    }
}
