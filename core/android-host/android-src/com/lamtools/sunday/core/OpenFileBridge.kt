package com.lamtools.sunday.core

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.util.Log
import androidx.core.content.FileProvider
import java.io.File

/**
 * Opens a file the app holds with whatever the system has for it.
 *
 * Android will not hand a `file://` path to another app: that has been refused since API 24
 * because it would let any app read any file the caller can. The way through is a content
 * URI from a FileProvider, with a one-off read grant for the receiving app — that is, the
 * app lends exactly one file, for as long as the viewer uses it.
 *
 * A file outside the provider's roots (the attachment store lives next to `files/` rather
 * than inside it) is copied into `files/open/` first. Copying a document to hand it to a
 * viewer is cheaper than widening the provider to the whole data directory.
 */
object OpenFileBridge {
  private const val TAG = "SundayOpen"
  private const val AUTHORITY_SUFFIX = ".fileprovider"
  private const val MAX_BYTES = 50L * 1024 * 1024

  init {
    System.loadLibrary("sunday_android_host_lib")
    nativeRegister()
  }

  @JvmStatic external fun nativeRegister()

  /**
   * Opens the file at [path] and returns a reason when it could not be opened.
   *
   * Called from Rust: a failure is reported as text rather than an exception so the caller
   * can put it on screen instead of logging it into nowhere.
   */
  @JvmStatic
  fun open(path: String, mime: String): String {
    val host = MainActivity.current() ?: return "应用界面还没有准备好"
    val source = File(path)
    if (!source.isFile) return "原文件不存在"
    if (source.length() > MAX_BYTES) return "文件超过 ${MAX_BYTES / (1024 * 1024)} MB，先用预览打开"
    return try {
      val shared = shareableCopy(host, source)
      val authority = host.packageName + AUTHORITY_SUFFIX
      val uri: Uri = FileProvider.getUriForFile(host, authority, shared)
      val intent = Intent(Intent.ACTION_VIEW).apply {
        setDataAndType(uri, mime.ifEmpty { "application/octet-stream" })
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
      }
      host.startActivity(intent)
      ""
    } catch (error: ActivityNotFoundException) {
      Log.w(TAG, "no app handles ${source.name}", error)
      "这台设备上没有能打开这种文件的应用"
    } catch (error: Throwable) {
      Log.e(TAG, "cannot open $path", error)
      "${error.javaClass.simpleName}: ${error.message}"
    }
  }

  /**
   * A copy the provider is allowed to hand out.
   *
   * The provider this app ships declares the cache directory, so a file already under it is
   * shared in place and anything else is staged there. The staging folder is emptied each
   * time: these copies exist to be lent to a viewer, not to be kept.
   */
  private fun shareableCopy(host: MainActivity, source: File): File {
    val cacheDir = host.cacheDir
    if (source.canonicalPath.startsWith(cacheDir.canonicalPath + File.separator)) {
      return source
    }
    val staging = File(cacheDir, "open")
    staging.listFiles()?.forEach { it.delete() }
    staging.mkdirs()
    val target = File(staging, source.name)
    source.copyTo(target, overwrite = true)
    return target
  }
}
