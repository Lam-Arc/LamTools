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
 * [Why the manifest is compared, not merely checked] An earlier version returned as soon
 * as a manifest existed, so a new APK with a fixed image kept running the old one on every
 * device that had already installed: the file was there, and nothing ever compared what it
 * said. The packaged manifest's `runtimeVersion` is the only signal that the image changed.
 *
 * [Why it is written last] Its presence means "the archive is here". Copying the archive
 * first and the manifest second means a killed copy leaves the old manifest, and the next
 * launch simply tries again.
 */
object RuntimeAssets {
  private const val BUFFER = 256 * 1024

  /** Runs on a background thread; the caller must not block the main thread on it. */
  @JvmStatic
  fun ensure(context: Context) {
    val dir = File(context.filesDir, "runtime")
    val manifest = File(dir, "runtime-manifest.json")
    try {
      val packagedText = context.assets.open("runtime/manifest.json").bufferedReader().use { it.readText() }
      val packaged = JSONObject(packagedText)
      val packagedVersion = packaged.optString("runtimeVersion")
      val installedVersion = if (manifest.isFile && manifest.length() > 0L) {
        runCatching { JSONObject(manifest.readText()).optString("runtimeVersion") }.getOrDefault("")
      } else {
        ""
      }
      if (installedVersion == packagedVersion && packagedVersion.isNotEmpty()) return

      dir.mkdirs()
      val name = packaged.optString("rootfs")
      if (name.isEmpty()) return
      val archive = File(dir, name)
      // Overwrite: the archive name does not change between builds, only its contents.
      val tempArchive = File(dir, "$name.part")
      copy(context, "runtime/$name", tempArchive)
      if (!tempArchive.renameTo(archive)) {
        tempArchive.delete()
        android.util.Log.e("SundayRuntime", "could not place $name")
        return
      }

      val tempManifest = File(dir, "runtime-manifest.json.part")
      tempManifest.writeText(packagedText)
      if (!tempManifest.renameTo(manifest)) {
        tempManifest.delete()
      }
      android.util.Log.i("SundayRuntime", "runtime staged: $packagedVersion")
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
