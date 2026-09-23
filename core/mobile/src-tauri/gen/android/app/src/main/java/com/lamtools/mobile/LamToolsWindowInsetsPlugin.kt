package com.lamtools.mobile

import android.app.Activity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import app.tauri.annotation.Command
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin

/**
 * Exposes the edge-to-edge system-bar insets in CSS-pixel units.
 *
 * Android reports WindowInsets in physical pixels while a WebView lays out in
 * CSS pixels. Keeping the conversion here means the web layer can use the
 * value directly in a custom property and does not need device-density logic.
 */
@TauriPlugin
class LamToolsWindowInsetsPlugin(private val activity: Activity) : Plugin(activity) {
    @Command
    fun get(invoke: Invoke) {
        try {
            val insets = ViewCompat.getRootWindowInsets(activity.window.decorView)
                ?: run {
                    invoke.reject("window insets unavailable")
                    return
                }
            val statusBars = insets.getInsets(WindowInsetsCompat.Type.statusBars())
            val stableStatusBars = insets.getInsetsIgnoringVisibility(WindowInsetsCompat.Type.statusBars())
            val cutout = insets.getInsets(WindowInsetsCompat.Type.displayCutout())
            val density = activity.resources.displayMetrics.density
            if (density <= 0f) {
                invoke.reject("invalid display density")
                return
            }
            val result = JSObject()
            // Edge-to-edge can briefly expose a zero visible inset while the
            // decor view is attaching. The stable inset and Android status
            // bar dimension keep the web title below a visible system bar.
            val top = maxOf(statusBars.top, stableStatusBars.top, cutout.top, statusBarHeightPx())
            result.put("top", cssPixels(top, density))
            result.put("right", cssPixels(maxOf(statusBars.right, cutout.right), density))
            result.put("bottom", cssPixels(maxOf(statusBars.bottom, cutout.bottom), density))
            result.put("left", cssPixels(maxOf(statusBars.left, cutout.left), density))
            invoke.resolve(result)
        } catch (error: Exception) {
            invoke.reject(error.message ?: "window inset read failed")
        }
    }

    private fun cssPixels(value: Int, density: Float): Double = value.toDouble() / density

    private fun statusBarHeightPx(): Int {
        val id = activity.resources.getIdentifier("status_bar_height", "dimen", "android")
        return if (id > 0) activity.resources.getDimensionPixelSize(id) else 0
    }
}
