package com.lamtools.mobile

import android.app.Activity
import android.app.DownloadManager
import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.Context
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

@InvokeArg
class ShellDownloadArgs {
    lateinit var url: String
    lateinit var fileName: String
}

@InvokeArg
class ShellDownloadIdArgs {
    lateinit var id: String
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

    /**
     * The verified APK, wherever it landed: the system downloader writes to the
     * app's external files directory, the in-process fallback to the cache.
     */
    private fun resolveUpdateFile(fileName: String): File {
        val candidates = listOfNotNull(
            activity.getExternalFilesDir(null)?.let { File(it, "sunday-updates") },
            File(activity.cacheDir, "sunday-updates"),
        )
        for (directory in candidates) {
            val canonical = directory.canonicalFile
            val file = File(canonical, fileName).canonicalFile
            if (file.parentFile == canonical && file.isFile && file.length() > 0L) return file
        }
        throw IllegalArgumentException("update file is not there")
    }

    private fun safeUpdateName(value: String): String {
        require(value.matches(Regex("[A-Za-z0-9._-]{1,120}\\.apk")))
        return value
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

    /**
     * Hand the download to the system service.
     *
     * The transfer then belongs to Android, not to this process: it keeps going
     * when the app is backgrounded or killed, shows up in the notification shade,
     * and only needs the app again once the file is there to verify and install.
     */
    @Command
    fun startDownload(invoke: Invoke) {
        try {
            val args = invoke.parseArgs(ShellDownloadArgs::class.java)
            val uri = Uri.parse(args.url)
            require(uri.scheme == "https")
            val fileName = safeUpdateName(args.fileName)
            // VISIBILITY_VISIBLE keeps the progress notification but drops the
            // "tap to install" one at the end: the app verifies the bytes against
            // the release digest first, so the finished file must not have a
            // shortcut around that check.
            val request = DownloadManager.Request(uri)
                .setTitle(fileName)
                .setDescription("Sunday 更新")
                .setMimeType("application/vnd.android.package-archive")
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE)
                .setDestinationInExternalFilesDir(activity, null, "sunday-updates/$fileName")
            // The system downloader creates the file, not the parents: make the
            // directory first so a nested destination cannot fail the enqueue.
            File(activity.getExternalFilesDir(null), "sunday-updates").mkdirs()
            val manager = activity.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
            val id = manager.enqueue(request)
            require(id > 0L)
            // The host verifies the bytes itself, so it needs to know where the
            // system put them without asking Android for a content URI.
            val directory = File(activity.getExternalFilesDir(null), "sunday-updates").canonicalPath
            invoke.resolve(
                JSObject()
                    .put("id", id.toString())
                    .put("fileName", fileName)
                    .put("directory", directory)
            )
        } catch (_: Exception) {
            invoke.reject("无法交给系统下载")
        }
    }

    /** How the system download is doing, by the id it was given. */
    @Command
    fun downloadState(invoke: Invoke) {
        try {
            val args = invoke.parseArgs(ShellDownloadIdArgs::class.java)
            val id = args.id.toLongOrNull() ?: throw IllegalArgumentException("bad id")
            val manager = activity.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
            val cursor = manager.query(DownloadManager.Query().setFilterById(id))
            val result = JSObject().put("state", "unknown").put("received", 0).put("total", 0).put("reason", "")
            cursor.use { rows ->
                if (rows != null && rows.moveToFirst()) {
                    val status = rows.getInt(rows.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS))
                    val received = rows.getInt(rows.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR))
                    val total = rows.getInt(rows.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES))
                    val reason = rows.getInt(rows.getColumnIndexOrThrow(DownloadManager.COLUMN_REASON))
                    result.put("state", when (status) {
                        DownloadManager.STATUS_SUCCESSFUL -> "successful"
                        DownloadManager.STATUS_FAILED -> "failed"
                        else -> "downloading"
                    })
                    result.put("received", received.toLong())
                    result.put("total", total.toLong())
                    result.put("reason", reason.toString())
                }
            }
            invoke.resolve(result)
        } catch (_: Exception) {
            invoke.reject("无法读取下载进度")
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
