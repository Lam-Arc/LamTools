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

@InvokeArg
class AttachmentOpenArgs {
    lateinit var fileName: String
    lateinit var mimeType: String
}

@TauriPlugin
class LamToolsAttachmentOpenPlugin(private val activity: Activity) : Plugin(activity) {
    @Command
    fun cacheDirectory(invoke: Invoke) {
        try {
            val directory = File(activity.cacheDir, "sunday-attachments")
            if (!directory.exists()) directory.mkdirs()
            require(directory.isDirectory)
            invoke.resolve(JSObject().put("path", directory.canonicalPath))
        } catch (_: Exception) {
            invoke.reject("无法准备附件缓存")
        }
    }

    @Command
    fun open(invoke: Invoke) {
        try {
            val args = invoke.parseArgs(AttachmentOpenArgs::class.java)
            require(args.fileName.matches(Regex("[0-9a-f]{32}\\.[a-z0-9]{1,10}")))
            require(args.mimeType.length in 3..128 && args.mimeType.contains('/'))
            val directory = File(activity.cacheDir, "sunday-attachments").canonicalFile
            val file = File(directory, args.fileName).canonicalFile
            require(file.parentFile == directory && file.isFile)
            val uri = FileProvider.getUriForFile(
                activity,
                "${activity.packageName}.fileprovider",
                file,
            )
            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, args.mimeType)
                clipData = ClipData.newUri(activity.contentResolver, args.fileName, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            activity.startActivity(Intent.createChooser(intent, "打开附件"))
            invoke.resolve(JSObject().put("opened", true))
        } catch (_: Exception) {
            invoke.reject("无法使用系统应用打开附件")
        }
    }
}
