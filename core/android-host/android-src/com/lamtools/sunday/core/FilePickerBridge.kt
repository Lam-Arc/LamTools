package com.lamtools.sunday.core

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import android.util.Log
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.FileProvider
import java.io.File
import java.lang.ref.WeakReference
import org.json.JSONArray
import org.json.JSONObject

/**
 * The system document picker, and the copy that makes its answer usable by the core.
 *
 * A `content://` URI is a permission, not a file: it belongs to another app that may
 * move or delete the object whenever it likes, and the guest cannot read it at all. So
 * the picker copies the bytes into this app's own storage during the grant, under the
 * one directory the guest sees (`files/runtime/userdata` is mounted at `/root/.sunday`),
 * and Rust answers the in-guest path. Nothing downstream holds a URI.
 *
 * user:“使用 Android SAF 桥接现有 Python Core 附件接口”+(选中的文件落到核心能读到的
 * 目录，然后交给核心现有的附件登记接口；附件本身仍然由 Python Core 记录和读取，
 * 这里不实现任何附件业务)。
 *
 * The copy is also where the size limit is enforced: refusing after writing two
 * gigabytes is not a limit, it is a delay. Core applies the same number on its side.
 */
object FilePickerBridge {
  private const val TAG = "SundayFiles"
  private const val MAX_BYTES = 50L * 1024 * 1024

  private var host: WeakReference<MainActivity>? = null
  private var documents: ActivityResultLauncher<Array<String>>? = null
  private var capture: ActivityResultLauncher<Uri>? = null
  private var pending = ""
  private var pendingSource = "file"
  private var pendingCapture: File? = null

  init {
    System.loadLibrary("sunday_android_host_lib")
    nativeRegister()
  }

  @JvmStatic external fun nativeRegister()

  /** Rust's answer channel. Exactly one message per request id. */
  @JvmStatic external fun nativeDeliver(requestId: String, payload: String)

  /**
   * Registers the result contracts. Called from `MainActivity.onCreate`, because a
   * contract has to be registered before the activity is started.
   */
  @JvmStatic
  fun attach(activity: MainActivity) {
    host = WeakReference(activity)
    documents = activity.registerForActivityResult(
      ActivityResultContracts.OpenMultipleDocuments(),
    ) { uris -> finishDocuments(uris) }
    capture = activity.registerForActivityResult(
      ActivityResultContracts.TakePicture(),
    ) { taken -> finishCapture(taken) }
  }

  /**
   * Opens the picker. Called over JNI from Rust, so the work moves to the UI thread.
   *
   * `source` is the composer's own vocabulary (`file`, `photos`, `camera`), so the one
   * attachment button keeps behaving like it does on desktop.
   */
  @JvmStatic
  fun pick(requestId: String, source: String, accept: String) {
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
    pendingSource = source
    activity.runOnUiThread {
      try {
        when (source) {
          "camera" -> takePhoto(activity, requestId)
          "photos" -> launchDocuments(arrayOf("image/*"))
          else -> launchDocuments(arrayOf(accept.ifEmpty { "*/*" }))
        }
      } catch (error: Throwable) {
        Log.e(TAG, "cannot open the file picker", error)
        finishWithError("${error.javaClass.simpleName}: ${error.message}")
      }
    }
  }

  private fun launchDocuments(mimeTypes: Array<String>) {
    val launcher = documents ?: throw IllegalStateException("文件选择器没有注册")
    // Any type: a session can hold text, images and PDFs, and narrowing here would make
    // the picker lie about what the app accepts.
    launcher.launch(mimeTypes)
  }

  /**
   * One photo into the app's cache, handed to the camera through the provider that is
   * already declared by the generated manifest. No storage permission is involved.
   */
  private fun takePhoto(activity: MainActivity, requestId: String) {
    val launcher = capture ?: throw IllegalStateException("相机没有注册")
    val target = File(activity.cacheDir, "capture-$requestId.jpg")
    val uri = FileProvider.getUriForFile(activity, "${activity.packageName}.fileprovider", target)
    pendingCapture = target
    launcher.launch(uri)
  }

  private fun finishDocuments(uris: List<Uri>?) {
    val request = takePending()
    if (request.isEmpty()) return
    val activity = host?.get()
    if (activity == null) {
      finishWithError("应用界面已经关闭")
      return
    }
    val chosen = uris ?: emptyList()
    if (chosen.isEmpty()) {
      // Cancelling is a decision, not a failure.
      deliverEmpty(request)
      return
    }
    val root = inboxFor(activity, request)
    val files = JSONArray()
    val failed = JSONArray()
    for ((index, uri) in chosen.withIndex()) {
      try {
        files.put(
          copyOne(
            activity.contentResolver,
            uri,
            File(root, index.toString()),
            displayName(activity.contentResolver, uri) ?: "file-$index",
            activity.contentResolver.getType(uri) ?: "application/octet-stream",
          ),
        )
      } catch (error: Throwable) {
        Log.e(TAG, "cannot import $uri", error)
        failed.put(
          JSONObject()
            .put("name", displayName(activity.contentResolver, uri) ?: "第 ${index + 1} 个文件")
            .put("reason", "${error.javaClass.simpleName}: ${error.message}"),
        )
      }
    }
    deliver(request, JSONObject().put("files", files).put("failed", failed).toString())
  }

  private fun finishCapture(taken: Boolean) {
    val request = takePending()
    val temporary = pendingCapture
    pendingCapture = null
    if (request.isEmpty()) return
    val activity = host?.get()
    if (activity == null) {
      temporary?.delete()
      finishWithError("应用界面已经关闭")
      return
    }
    if (!taken || temporary == null || !temporary.isFile) {
      temporary?.delete()
      deliverEmpty(request)
      return
    }
    try {
      val root = inboxFor(activity, request)
      val file = copyOne(activity.contentResolver, null, root, "photo-${System.currentTimeMillis()}.jpg", "image/jpeg", temporary)
      deliver(request, JSONObject().put("files", JSONArray().put(file)).put("failed", JSONArray()).toString())
    } catch (error: Throwable) {
      Log.e(TAG, "cannot import the captured photo", error)
      deliver(
        request,
        JSONObject()
          .put("files", JSONArray())
          .put("failed", JSONArray().put(JSONObject().put("name", "照片").put("reason", "${error.javaClass.simpleName}: ${error.message}")))
          .toString(),
      )
    } finally {
      temporary.delete()
    }
  }

  /**
   * Where an imported file lives for the rest of its life: the directory the guest
   * mounts as its own user data. Core only records the path, so deleting this copy
   * would break the attachment later.
   */
  private fun inboxFor(activity: MainActivity, requestId: String): File {
    val root = File(activity.filesDir, "runtime/userdata/inbox/$requestId")
    if (!root.mkdirs() && !root.isDirectory) throw IllegalStateException("无法创建暂存目录")
    return root
  }

  private fun copyOne(
    resolver: ContentResolver,
    uri: Uri?,
    directory: File,
    name: String,
    mime: String,
    source: File? = null,
  ): JSONObject {
    if (!directory.mkdirs() && !directory.isDirectory) throw IllegalStateException("无法创建目录")
    val target = File(directory, safeName(name))
    val input = source?.inputStream() ?: uri?.let { resolver.openInputStream(it) }
      ?: throw IllegalStateException("打不开这个文件")
    input.use { stream ->
      target.outputStream().use { output ->
        val buffer = ByteArray(64 * 1024)
        var total = 0L
        while (true) {
          val read = stream.read(buffer)
          if (read <= 0) break
          total += read
          if (total > MAX_BYTES) {
            target.delete()
            throw IllegalStateException("超过 ${MAX_BYTES / (1024 * 1024)} MB")
          }
          output.write(buffer, 0, read)
        }
      }
    }
    return JSONObject()
      .put("name", name)
      .put("path", target.absolutePath)
      .put("mime", mime)
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

  private fun takePending(): String {
    val request = pending
    pending = ""
    return request
  }

  private fun deliverEmpty(request: String) {
    deliver(request, JSONObject().put("files", JSONArray()).put("failed", JSONArray()).toString())
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
