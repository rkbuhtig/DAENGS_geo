package com.daengs.geo.walk

import android.content.ClipData
import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import java.io.File

/**
 * Hands the exported walk files to whatever app the developer picks — mail, chat, Drive, Files.
 *
 * **Why this exists**: without it the exports sit in app-internal storage, reachable only through
 * `adb run-as`. That means a walk can only be looked at by cabling the phone to the one PC that
 * has the SDK. Field measurement happens away from that PC, so the phone itself has to be able to
 * send the session somewhere.
 *
 * Debug only. The caller gates on `BuildConfig.DEBUG` and the provider is declared in the debug
 * manifest, so the share path does not exist in release at all — [shareIntent] there would throw
 * from `FileProvider.getUriForFile` (no provider metadata for the authority) rather than return
 * null. Both lines have to hold; neither is a fallback for the other.
 */
object WalkExportShare {

    private const val AUTHORITY_SUFFIX = ".walkexports"
    private const val MIME = "application/json"

    /** Newest first — the walk you just finished is the one you almost always want. */
    fun exports(context: Context): List<File> =
        File(context.filesDir, WalkSessionExporter.DIRECTORY)
            .listFiles { file -> file.isFile && file.name.endsWith(".json") }
            ?.sortedByDescending(File::lastModified)
            .orEmpty()

    /**
     * A chooser-ready intent for [files], or null when there is nothing to send.
     *
     * Files travel as content URIs with read permission granted for this intent only — the
     * receiving app never sees a path into our storage.
     */
    fun shareIntent(context: Context, files: List<File>): Intent? {
        if (files.isEmpty()) return null
        val uris = ArrayList(
            files.map {
                FileProvider.getUriForFile(context, context.packageName + AUTHORITY_SUFFIX, it)
            },
        )
        val send = if (uris.size == 1) {
            Intent(Intent.ACTION_SEND).putExtra(Intent.EXTRA_STREAM, uris[0])
        } else {
            Intent(Intent.ACTION_SEND_MULTIPLE).putParcelableArrayListExtra(
                Intent.EXTRA_STREAM, uris,
            )
        }
        // ClipData 로도 붙인다. `EXTRA_STREAM` 만 두면 공유 시트 자신이 URI 를 못 읽어
        // 미리보기 단계에서 권한 거부가 난다 — 받는 앱은 되지만 로그가 지저분하고,
        // 시트가 파일명을 못 보여주는 기기가 있다. 권한 전파는 ClipData 가 담당한다.
        send.clipData = ClipData.newUri(context.contentResolver, MIME, uris[0]).apply {
            uris.drop(1).forEach { addItem(ClipData.Item(it)) }
        }
        return Intent.createChooser(
            send.setType(MIME)
                .putExtra(Intent.EXTRA_SUBJECT, "DAENGS 산책 기록 ${files.size}건")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION),
            "산책 기록 보내기",
        ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }
}
