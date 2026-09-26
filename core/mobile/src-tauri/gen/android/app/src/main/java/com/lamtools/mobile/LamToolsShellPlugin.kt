package com.lamtools.mobile

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import java.io.File

@InvokeArg
class ShellUrlArgs {
    lateinit var url: String
}

@InvokeArg
class ShellFileArgs {
    lateinit var fileName: String
}

/**
 * Hand work to the system: open an external link, or give a verified APK to the
 * package installer.
 *
 * Both actions exist because the app's own WebView can do neither. It is
 * cross-origin to the release site, so a link would navigate the app itself
 * instead of leaving it; and Android never installs a package silently — the
 * installer is a system screen the user confirms, which is exactly why the
 * app declares REQUEST_INSTALL_PACKAGES and then hands the file over rather
 * than pretending it can install.
 */
@TauriPlugin
class LamToolsShellPlugin(private val activity: Activity) : Plugin(activity) {
    @Command
    fun updatesDirectory(invoke: Invoke) {
        try {
            val directory = File(activity.cacheDir, "sunday-updates")
            if (!directory.exists()) directory.mkdirs()
            require(directory.isDirectory)
            invoke.resolve(JSObject().put("path", directory.canonicalPath))
        } catch (_: Exception) {
            invoke.reject("无法准备更新缓存")
        }
    }

    @Command
    fun openUrl(invoke: Invoke) {
        try {
            val args = invoke.parseArgs(ShellUrlArgs::class.java)
            val uri = Uri.parse(args.url)
            require(uri.scheme == "http" || uri.scheme == "https")
            activity.startActivity(Intent(Intent.ACTION_VIEW, uri))
            invoke.resolve(JSObject().put("opened", true))
        } catch (_: Exception) {
            invoke.reject("无法打开链接")
        }
    }

    @Command
    fun installApk(invoke: Invoke) {
        try {
            val args = invoke.parseArgs(ShellFileArgs::class.java)
            // Only a file the host downloaded into this directory and verified
            // against the manifest hash can reach the installer.
            require(args.fileName.matches(Regex("[A-Za-z0-9._-]{1,120}\\.apk")))
            val directory = File(activity.cacheDir, "sunday-updates").canonicalFile
            val file = File(directory, args.fileName).canonicalFile
            require(file.parentFile == directory && file.isFile && file.length() > 0L)
            val uri = FileProvider.getUriForFile(
                activity,
                "${activity.packageName}.fileprovider",
                file,
            )
            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, "application/vnd.android.package-archive")
                clipData = ClipData.newUri(activity.contentResolver, args.fileName, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            activity.startActivity(intent)
            invoke.resolve(JSObject().put("launched", true))
        } catch (_: ActivityNotFoundException) {
            invoke.reject("系统安装器不可用")
        } catch (_: Exception) {
            invoke.reject("无法启动系统安装器")
        }
    }
}
