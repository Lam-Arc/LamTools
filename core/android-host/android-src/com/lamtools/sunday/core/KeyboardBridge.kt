package com.lamtools.sunday.core

import android.util.Log
import android.view.View
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import java.lang.ref.WeakReference
import kotlin.math.roundToInt

/**
 * How much of the window the keyboard covers.
 *
 * The app draws edge to edge, so the window is not resized when the keyboard appears: the
 * webview keeps its full height and the composer ends up underneath the keys. The shared
 * interface already handles this for its own platforms — `useComposerLayout` reads
 * `--native-keyboard-inset` — so this bridge only has to publish the number Android knows
 * and nothing else.
 *
 * Values are CSS pixels: `WindowInsetsCompat` reports physical pixels, and the stylesheet
 * layering those insets works in CSS pixels.
 */
object KeyboardBridge {
  private const val TAG = "SundayKeyboard"

  private var host: WeakReference<MainActivity>? = null
  private var lastPublished = -1

  init {
    System.loadLibrary("sunday_android_host_lib")
    nativeRegister()
  }

  @JvmStatic external fun nativeRegister()

  /** Rust's channel: one inset change, already in CSS pixels. */
  @JvmStatic external fun nativePublish(insetDp: Int)

  /**
   * Starts watching. Called from `MainActivity.onCreate`.
   *
   * The listener only reads the IME inset and returns the same insets it was given, so it
   * cannot change how the webview is laid out; the interface does that itself.
   */
  @JvmStatic
  fun watch(activity: MainActivity) {
    host = WeakReference(activity)
    val root = activity.findViewById<View>(android.R.id.content) ?: return
    ViewCompat.setOnApplyWindowInsetsListener(root) { _, insets ->
      publish(activity, insets.getInsets(WindowInsetsCompat.Type.ime()).bottom)
      insets
    }
    // The insets may already be known: reading them once here saves the interface from
    // starting up with a wrong offset.
    ViewCompat.getRootWindowInsets(root)?.let { insets ->
      publish(activity, insets.getInsets(WindowInsetsCompat.Type.ime()).bottom)
    }
  }

  private fun publish(activity: MainActivity, physicalBottom: Int) {
    val density = activity.resources.displayMetrics.density.takeIf { it > 0f } ?: 1f
    val cssPixels = (physicalBottom / density).roundToInt().coerceAtLeast(0)
    if (cssPixels == lastPublished) return
    lastPublished = cssPixels
    try {
      nativePublish(cssPixels)
    } catch (error: Throwable) {
      // The library is gone (process teardown) or Rust is not listening yet; the next
      // layout pass publishes again.
      Log.w(TAG, "cannot publish the keyboard inset", error)
    }
  }
}
