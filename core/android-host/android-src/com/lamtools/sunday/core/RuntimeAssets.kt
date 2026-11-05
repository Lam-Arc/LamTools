package com.lamtools.sunday.core

import android.content.Context
import org.json.JSONObject
import java.io.File

/**
 * Copies the packaged Linux runtime out of the APK's assets into the app's own files.
 *
 * [Why this is Kotlin and not Rust] Assets are not files. They live inside the APK and are
 * only reachable through `AssetManager`, whose C counterpart (`AAssetManager`) is reached
 * over JNI; a 200 MB archive cannot be read as `ByteArray` because the app would have to
 * hold all of it in memory, which an Android process will not survive. Streaming the copy
 * on the platform side, with the same buffers the platform already uses, is the shortest
 * path that also has a bounded memory footprint.
 *
 * [Why a marker file] The host asks "is the runtime ready" by looking for the manifest.
 * Copying the archive before the manifest would leave a window where an installed archive
 * looks usable; copying the manifest last makes its presence mean "everything is here".
 */
object RuntimeAssets {
  private const val BUFFER = 256 * 1024

  /** Runs on a background thread; the caller must not block the main thread on it. */
  @JvmStatic
  fun ensure(context: Context) {
    val dir = File(context.filesDir, "runtime")
    val manifest = File(dir, "runtime-manifest.json")
    try {
      if (manifest.isFile && manifest.length() > 0L) return
      dir.mkdirs()
      val tempManifest = File(dir, "runtime-manifest.json.part")
      copy(context, "runtime/manifest.json", tempManifest)
      val name = JSONObject(tempManifest.readText()).optString("rootfs")
      if (name.isEmpty()) {
        tempManifest.delete()
        return
      }
      val archive = File(dir, name)
      if (!archive.isFile || archive.length() == 0L) {
        val tempArchive = File(dir, "$name.part")
        copy(context, "runtime/$name", tempArchive)
        if (!tempArchive.renameTo(archive)) {
          tempArchive.delete()
          return
        }
      }
      // Manifest last: its presence is the "ready" signal the host polls for.
      if (!tempManifest.renameTo(manifest)) {
        tempManifest.delete()
      }
    } catch (error: Throwable) {
      android.util.Log.e("SundayRuntime", "could not stage the runtime: ${error.message}")
    }
  }

  private fun copy(context: Context, asset: String, dest: File) {
    context.assets.open(asset).use { source ->
      dest.outputStream().buffered(BUFFER).use { sink ->
        val buffer = ByteArray(BUFFER)
        while (true) {
          val read = source.read(buffer)
          if (read <= 0) break
          sink.write(buffer, 0, read)
        }
        sink.flush()
      }
    }
  }
}
