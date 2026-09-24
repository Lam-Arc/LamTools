package com.lamtools.mobile

import android.app.Activity
import android.content.ClipData
import android.content.Intent
import androidx.core.content.FileProvider
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import java.io.File
import java.io.FileOutputStream
import java.nio.charset.StandardCharsets

private const val DIAGNOSTICS_FILE_NAME = "sunday-mobile-diagnostics.json"
private const val MAX_DIAGNOSTICS_BYTES = 256 * 1024

@InvokeArg
class DiagnosticsShareArgs { lateinit var contents: String }

@TauriPlugin
class LamToolsDiagnosticsSharePlugin(private val activity: Activity) : Plugin(activity) {
    @Command
    fun share(invoke: Invoke) {
        try {
            val args = invoke.parseArgs(DiagnosticsShareArgs::class.java)
            val bytes = args.contents.toByteArray(StandardCharsets.UTF_8)
            require(bytes.isNotEmpty() && bytes.size <= MAX_DIAGNOSTICS_BYTES) {
                "diagnostics export is empty or too large"
            }

            val file = File(activity.cacheDir, DIAGNOSTICS_FILE_NAME)
            FileOutputStream(file, false).use { output ->
                output.write(bytes)
                output.fd.sync()
            }

            val uri = FileProvider.getUriForFile(
                activity,
                "${activity.packageName}.fileprovider",
                file,
            )
            val send = Intent(Intent.ACTION_SEND).apply {
                type = "application/json"
                putExtra(Intent.EXTRA_STREAM, uri)
                clipData = ClipData.newUri(activity.contentResolver, DIAGNOSTICS_FILE_NAME, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            activity.startActivity(Intent.createChooser(send, "分享诊断日志"))
            invoke.resolve(JSObject().put("shared", true))
        } catch (_: Exception) {
            // Keep file paths and exception messages out of the WebView and logs.
            invoke.reject("无法打开 Android 分享面板")
        }
    }
}
