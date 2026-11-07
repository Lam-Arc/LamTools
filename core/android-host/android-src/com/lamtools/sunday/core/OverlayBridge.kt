package com.lamtools.sunday.core

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.widget.Toast

/**
 * The host's side of the floating ring and the small window.
 *
 * user:“手机悬浮环：可拖动的悬浮按钮 + 操作态 + 任意处长按浮出 Pin 环 + 滑动选择 + 扇区
 * 动作落地”+(所以这里只回答三件事：能不能画悬浮窗、开/关悬浮服务、进小窗；环怎么画、
 * 选哪个扇区全部在 [SundayOverlayService] 与 [OverlayRingView] 里)。
 *
 * Rust reaches this object through `#[no_mangle]` symbols; every `external fun` below has
 * exactly one counterpart in `src-tauri/src/android_jni.rs`, and a missing one is an
 * `UnsatisfiedLinkError` at the first `OverlayBridge` reference — which is inside
 * `MainActivity.onCreate`, so the launcher would not start at all.
 */
object OverlayBridge {
  /** Extra carrying the sector action id; read by `MainActivity`. */
  const val EXTRA_ACTION = "sunday.overlay.action"

  /** Extra carrying the text a sector wants in the composer; read by `MainActivity`. */
  const val EXTRA_TEXT = "sunday.overlay.text"

  private var context: Context? = null

  init {
    System.loadLibrary("sunday_android_host_lib")
    nativeRegister()
  }

  /** Hands Rust the JavaVM and this class, so commands can call the methods below. */
  @JvmStatic external fun nativeRegister()

  /**
   * One state report: permission, whether the service is alive, whether the user wants it.
   *
   * user:“回到应用在 onResume 重查并 emit overlay-permission，界面据此刷新状态”+
   * (所以三件事一起报：只报权限的话，界面就不知道服务已经被系统杀掉了)。
   */
  @JvmStatic external fun nativeState(granted: Boolean, running: Boolean, wanted: Boolean)

  /** Called from `MainActivity.onCreate`: this object needs a context for a stopped app. */
  @JvmStatic
  fun attach(applicationContext: Context) {
    context = applicationContext
  }

  /** Whether the user granted "display over other apps". */
  @JvmStatic
  fun canDrawOverlays(): Boolean {
    val context = context ?: MainActivity.current() ?: return false
    // `requestPermissions` cannot grant this: it only exists as a special app access.
    return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) Settings.canDrawOverlays(context) else true
  }

  /** Opens the system page that owns that switch. */
  @JvmStatic
  fun openPermissionSettings() {
    val context = context ?: MainActivity.current() ?: return
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return
    try {
      val intent = Intent(
        Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
        Uri.parse("package:${context.packageName}"),
      ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
      context.startActivity(intent)
    } catch (error: Throwable) {
      Toast.makeText(context, "无法打开悬浮窗权限设置", Toast.LENGTH_SHORT).show()
    }
  }

  @JvmStatic
  fun start() {
    val context = context ?: return
    SundayOverlayService.start(context)
  }

  @JvmStatic
  fun stop() {
    val context = context ?: return
    SundayOverlayService.stop(context)
  }

  @JvmStatic
  fun running(): Boolean = SundayOverlayService.running

  @JvmStatic
  fun wanted(): Boolean = context?.let { SundayOverlayService.wanted(it) } ?: false

  /**
   * Enters the small window, or brings the app forward when the device cannot.
   *
   * user:“优先进入画中画（PiP），进不去时把 Sunday 自身切回前台”+(所以拒绝路径不是静默
   * 返回 false：用户必须看到一句「当前设备不支持小窗」，并且应用回到前台而不是停在小窗按钮)。
   */
  @JvmStatic
  fun enterPip(): Boolean {
    val activity = MainActivity.current() ?: return false
    return activity.enterSmallWindow()
  }

  /**
   * Reports the state the interface needs. Called from `MainActivity.onResume`.
   *
   * Missing the native library is not fatal: the interface also asks for the state as a
   * command, so a failed report only costs one refresh.
   */
  @JvmStatic
  fun reportState() {
    try {
      nativeState(canDrawOverlays(), running(), wanted())
    } catch (error: Throwable) {
      // Process teardown, or Rust before Tauri's setup. The command answers the same three
      // facts, so nothing is lost.
    }
  }

  /**
   * Hands one sector action to the interface: the service calls this on the UI thread.
   *
   * The action travels as an activity intent instead of a direct JNI call so the same path
   * works when the activity does not exist yet — opening the task is what the user asked
   * for anyway, and `onCreate`/`onNewIntent` both read the extras.
   */
  @JvmStatic
  fun deliver(action: String, text: String) {
    val context = context ?: MainActivity.current() ?: return
    try {
      val intent = Intent(context, MainActivity::class.java)
        .addFlags(
          Intent.FLAG_ACTIVITY_NEW_TASK
            or Intent.FLAG_ACTIVITY_SINGLE_TOP
            or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT,
        )
        .putExtra(EXTRA_ACTION, action)
        .putExtra(EXTRA_TEXT, text)
      context.startActivity(intent)
    } catch (error: Throwable) {
      Toast.makeText(context, "无法打开 Sunday", Toast.LENGTH_SHORT).show()
    }
  }
}
