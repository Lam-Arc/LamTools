package com.lamtools.sunday.core

import android.util.Log
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat

/**
 * How much of the screen the keyboard covers, reported to the interface.
 *
 * The window does not shrink when the keyboard opens: the app draws edge to edge, so the
 * WebView keeps its full height and the shared stylesheet cannot see the keyboard at all.
 * Without this the composer sits behind the keyboard, which on a phone means the input
 * field is on screen but unreachable, and every keystroke lands somewhere else.
 *
 * The value is published in density-independent pixels, because that is the unit the
 * stylesheet is written in on a device with a non-1.0 density.
 */
object KeyboardBridge {
  private const val TAG = "SundayKeyboard"

  init {
    System.loadLibrary("sunday_android_host_lib")
    nativeRegister()
  }

  @JvmStatic external fun nativeRegister()

  /** Reports the covered height in dp. Zero means the keyboard is closed. */
  @JvmStatic external fun nativePublish(insetDp: Int)

  /** Watches this activity's insets. Called from `MainActivity.onCreate`. */
  @JvmStatic
  fun watch(activity: MainActivity) {
    val density = activity.resources.displayMetrics.density.takeIf { it > 0f } ?: 1f
    val root = activity.window.decorView
    ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
      try {
        val ime = insets.getInsets(WindowInsetsCompat.Type.ime()).bottom
        val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars()).bottom
        // The keyboard inset already includes the navigation bar area, but not every
        // device reports it that way; taking the larger of the two keeps one meaning.
        val covered = maxOf(ime, bars)
        nativePublish(Math.round(covered / density).toInt())
      } catch (error: Throwable) {
        // A window that cannot answer insets is not a reason to lose the input field's
        // other behaviour; report nothing and keep the previous value.
        Log.w(TAG, "cannot read the keyboard inset", error)
      }
      ViewCompat.onApplyWindowInsets(view, insets)
      insets
    }
    ViewCompat.requestApplyInsets(root)
  }
}
