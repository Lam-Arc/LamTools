package com.lamtools.sunday.core

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import android.util.Log
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import java.io.File
import java.lang.ref.WeakReference
import org.json.JSONArray
import org.json.JSONObject

/**
 * The system document picker, and the copy that makes its answer usable.
 *
 * A `content://` URI is a permission, not a file. It stays readable while this activity
 * lives and not a moment longer unless a persistable grant is taken, and the object
 * behind it belongs to another app that may move or delete it whenever it likes. So the
 * picker copies the bytes into this app's own directory during the grant, and Rust only
 * ever sees real paths. Nothing downstream holds a URI, which is why a session reopened a
 * week later still opens its attachments.
 *
 * The copy is also where the size limit is enforced: refusing after copying two gigabytes
 * into the cache is not a limit, it is a delay.
 */
object FilePickerBridge {
  private const val TAG = "SundayFiles"
  private const val MAX_BYTES = 50L * 1024 * 1024

  private var host: WeakReference<MainActivity>? = null
  private var launcher: ActivityResultLauncher<Array<String>>? = null
  private var pending = ""

  init {
    System.loadLibrary("sunday_android_host_lib")
    nativeRegister()
  }

  @JvmStatic external fun nativeRegister()

  /** Rust's answer channel. Exactly one message per request id. */
  @JvmStatic external fun nativeDeliver(requestId: String, payload: String)

  /**
   * Registers the result contract. Called from `MainActivity.onCreate`, because the
   * contract has to be registered before the activity is started.
   */
  @JvmStatic
  fun attach(activity: MainActivity) {
    host = WeakReference(activity)
    launcher = activity.registerForActivityResult(
      ActivityResultContracts.OpenMultipleDocuments(),
    ) { uris -> finish(uris) }
  }

  /**
   * Opens the picker. Called over JNI from Rust, so the work moves to the UI thread.
   *
   * Nothing is launched when a picker is already open: two launchers would share the
   * `pending` slot and one caller would wait forever.
   */
  @JvmStatic
  fun pick(requestId: String) {
    val activity = host?.get()
    if (activity == null) {
      fail(requestId, "应用界面还没有准备好")
      return
    }
    if (pending.isNotEmpty()) {
      fail(requestId, "已经有一个文件选择器打开了")
      return
    }
    pending = requestId
    activity.runOnUiThread {
      try {
        val target = launcher ?: throw IllegalStateException("文件选择器没有注册")
        // Any type: a session can hold text, images and PDFs, and narrowing here would
        // make the picker lie about what the app accepts.
        target.launch(arrayOf("*/*"))
      } catch (error: Throwable) {
        Log.e(TAG, "cannot open the document picker", error)
        finishWithError("${error.javaClass.simpleName}: ${error.message}")
      }
    }
  }

  private fun finish(uris: List<Uri>?) {
    val request = pending
    pending = ""
    if (request.isEmpty()) return
    val activity = host?.get()
    if (activity == null) {
      finishWithError("应用界面已经关闭")
      return
    }
    val chosen = uris ?: emptyList()
    if (chosen.isEmpty()) {
      // Cancelling is a decision, not a failure.
      deliver(request, JSONObject().put("files", JSONArray()).put("failed", JSONArray()).toString())
      return
    }
    val root = File(activity.filesDir, "picked")
    // Only the latest pick is staged: an imported attachment has its own copy inside the
    // core, so keeping older staging directories would grow without ever being read.
    root.deleteRecursively()
    if (!root.mkdirs() && !root.isDirectory) {
      finishWithError("无法创建暂存目录")
      return
    }
    val files = JSONArray()
    val failed = JSONArray()
    for ((index, uri) in chosen.withIndex()) {
      try {
        files.put(copyOne(activity.contentResolver, uri, root, index))
      } catch (error: Throwable) {
        Log.e(TAG, "cannot import $uri", error)
        failed.put(
          JSONObject()
            .put("name", displayName(activity.contentResolver, uri) ?: "第 ${index + 1} 个文件")
            .put("reason", "${error.javaClass.simpleName}: ${error.message}"),
        )
      }
    }
    deliver(
      request,
      JSONObject().put("files", files).put("failed", failed).toString(),
    )
  }

  private fun copyOne(
    resolver: ContentResolver,
    uri: Uri,
    root: File,
    index: Int,
  ): JSONObject {
    val name = displayName(resolver, uri) ?: "file-$index"
    val directory = File(root, index.toString())
    if (!directory.mkdirs() && !directory.isDirectory) {
      throw IllegalStateException("无法创建目录")
    }
    val target = File(directory, safeName(name))
    resolver.openInputStream(uri).use { input ->
      if (input == null) throw IllegalStateException("打不开这个文件")
      target.outputStream().use { output ->
        val buffer = ByteArray(64 * 1024)
        var total = 0L
        while (true) {
          val read = input.read(buffer)
          if (read <= 0) break
          total += read
          if (total > MAX_BYTES) {
            throw IllegalStateException("超过 ${MAX_BYTES / (1024 * 1024)} MB")
          }
          output.write(buffer, 0, read)
        }
      }
    }
    return JSONObject()
      .put("name", name)
      .put("path", target.absolutePath)
      .put("mime", resolver.getType(uri) ?: "application/octet-stream")
      .put("size", target.length())
  }

  /** The name the user sees in their own file manager, not the URI's last segment. */
  private fun displayName(resolver: ContentResolver, uri: Uri): String? = try {
    resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
      if (cursor.moveToFirst()) {
        val column = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
        if (column >= 0) cursor.getString(column) else null
      } else {
        null
      }
    } ?: uri.lastPathSegment
  } catch (error: Throwable) {
    Log.w(TAG, "cannot read the display name of $uri", error)
    uri.lastPathSegment
  }

  /** Keeps the display name usable as a file name without changing what is shown. */
  private fun safeName(name: String): String {
    val cleaned = name.map { character ->
      when {
        character in "/\\:*?\"<>|" -> '_'
        character.isISOControl() -> '_'
        else -> character
      }
    }.joinToString("").trim().trim('.')
    return if (cleaned.isEmpty()) "attachment" else cleaned
  }

  private fun finishWithError(reason: String) {
    val request = pending
    pending = ""
    if (request.isEmpty()) return
    fail(request, reason)
  }

  private fun fail(request: String, reason: String) {
    deliver(request, JSONObject().put("error", reason).toString())
  }

  private fun deliver(request: String, payload: String) {
    try {
      nativeDeliver(request, payload)
    } catch (error: Throwable) {
      // Nothing is waiting any more, or the library is gone: either way the caller has
      // its own timeout and there is nothing useful left to do here.
      Log.w(TAG, "cannot deliver the picker result", error)
    }
  }
}
