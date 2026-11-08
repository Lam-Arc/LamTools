package com.lamtools.sunday.core

import android.app.PictureInPictureParams
import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.util.Rational
import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import android.widget.Toast
import androidx.activity.SystemBarStyle
import androidx.activity.enableEdgeToEdge
import org.json.JSONObject

class MainActivity : TauriActivity() {
  companion object {
    /** 与 index-android.html 的启动层底色一致，避免两段颜色对不上。 */
    private const val BOOT_SURFACE = "#070912"

    private var alive: java.lang.ref.WeakReference<MainActivity>? = null

    /** The activity, for a bridge that needs a context: opening a file, mostly. */
    fun current(): MainActivity? = alive?.get()

    /**
     * Puts the task in the background without touching the process.
     *
     * Called by the host after the interface reports that it has nothing left to close.
     */
    @JvmStatic
    fun background() {
      current()?.moveTaskToBack(true)
    }

    init {
      // Rust needs one fact from Android that it cannot read on its own: where the
      // packaged `.so` files were extracted. Since Android 10 a binary in app data
      // cannot be executed, but the same bytes under nativeLibraryDir can, and proot
      // is exactly such a binary.
      System.loadLibrary("sunday_android_host_lib")
    }
  }

  /** Hands `applicationInfo.nativeLibraryDir` to the host before anything starts. */
  private external fun nativeSetLibraryDir(path: String)

  /** Hands `filesDir` over: the host keeps its runtime and its database there. */
  private external fun nativeSetFilesDir(path: String)

  /**
   * Offers the back press to the interface.
   *
   * Returns true when the interface took it (it closed a full-area view), false when it
   * has nowhere to go and the task should simply move to the background.
   */
  private external fun nativeBack(): Boolean

  /**
   * One sector action from the floating ring, as JSON: `{"action":"question","text":"？"}`.
   *
   * user:“MainActivity 在 onCreate 与 onNewIntent 读取 → 调新 JNI nativeOverlayAction(json)
   * → Rust emit overlay-action”+(冷启动也走同一条路：进程可能是被悬浮环拉起来的)。
   */
  private external fun nativeOverlayAction(payload: String)

  /** 小窗进出：界面据此收窄布局，不再画全屏的头部。 */
  private external fun nativePipMode(active: Boolean)

  override fun onCreate(savedInstanceState: Bundle?) {
    alive = java.lang.ref.WeakReference(this)
    // Debug builds only: the DevTools socket is what `scripts/android_cdp.py` attaches to,
    // and it lets a support log show what the interface actually did. A release build must
    // never expose it, so the debuggable flag decides — not a constant someone can forget.
    if ((applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
      WebView.setWebContentsDebuggingEnabled(true)
    }
    // 启动层是深色，状态栏图标必须是浅色才看得见；界面本身是浅色主题，画完之后会
    // 自己再定一次，所以这里只负责第一屏。
    enableEdgeToEdge(
      statusBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
      navigationBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
    )
    nativeSetLibraryDir(applicationInfo.nativeLibraryDir)
    nativeSetFilesDir(filesDir.absolutePath)
    // Touch the keystore bridge before Tauri starts. Its initialiser is what hands the
    // JavaVM to Rust, and Kotlin only initialises an object when something refers to
    // it: Rust runs its setup inside `super.onCreate`, earlier than any callback.
    KeystoreBridge.register()
    // The floating ring asks for a context when no activity is guaranteed to exist, and
    // touching the object runs its initialiser, which is what hands the JavaVM to Rust.
    OverlayBridge.attach(applicationContext)
    // Staging the packaged runtime takes seconds the first time and does no work after
    // that; it must not delay the first frame, and the host waits for its marker before
    // it tries to install.
    Thread({ RuntimeAssets.ensure(applicationContext) }, "sunday-runtime-assets").start()
    super.onCreate(savedInstanceState)
    // user:“首屏启动的画面”+(WebView 在页面画出来之前会先铺一层白底，实测冷启动第 2 秒
    // 整屏纯白；窗口背景和 WebView 自身的底色都压成同一个近黑色，这一帧就不存在了)。
    paintBootSurface()
    // The file picker registers its result contract here, which has to happen before the
    // activity is started. Touching the object also runs its initialiser, which is what
    // hands the JavaVM to Rust.
    FilePickerBridge.attach(this)
    QrScanBridge.attach(this)
    // The window does not shrink for the keyboard (edge to edge), so the interface can
    // only learn how much it covers from here.
    KeyboardBridge.watch(this)
    // The ring was used while this process was gone: the action arrives with the intent
    // that started the activity, and it has to reach the interface before anything renders.
    consumeOverlayIntent(intent)
  }

  /**
   * The task was already alive: the ring's action arrives here instead of `onCreate`.
   *
   * `singleTask` guarantees this, so the activity is not rebuilt and the composer keeps
   * whatever the user had typed.
   */
  override fun onNewIntent(intent: Intent) {
    super.onNewIntent(intent)
    setIntent(intent)
    consumeOverlayIntent(intent)
  }

  /** Reads one sector action off the launch intent and hands it to the host. */
  private fun consumeOverlayIntent(intent: Intent?) {
    val action = intent?.getStringExtra(OverlayBridge.EXTRA_ACTION) ?: return
    intent.removeExtra(OverlayBridge.EXTRA_ACTION)
    val text = intent.getStringExtra(OverlayBridge.EXTRA_TEXT).orEmpty()
    intent.removeExtra(OverlayBridge.EXTRA_TEXT)
    try {
      val payload = JSONObject().put("action", action).put("text", text).toString()
      nativeOverlayAction(payload)
    } catch (error: Throwable) {
      Log.w("SundayOverlay", "cannot hand the overlay action to the host", error)
    }
  }

  /**
   * Focus was lost. This also fires for a rotation, for a split-screen divider drag
   * and for a permission dialog, so nothing here may be expensive: the host records a
   * timestamp and the guest re-reads its own state when the UI comes back.
   */
  /**
   * Back leaves the app in the background when there is nothing to go back to.
   *
   * The default ends the activity, and ending it kills the Linux runtime and the core
   * with it: a user who taps back on the start screen would lose the process that
   * holds their turns. Navigation inside the webview still works, because WryActivity
   * checks canGoBack() before calling this.
   */
  @Deprecated("WryActivity still routes back through this method")
  override fun onBackPressed() {
    // user:“大问题，返回不可用，我被困在设置页面了”+(返回先交给界面：它先关掉设置这类
    // 整版界面，只有真的没处可退时才把任务放到后台，绝不直接结束进程)。
    if (!nativeBack()) moveTaskToBack(true)
  }

  override fun onPause() {
    super.onPause()
    LifecycleBridge.signal("pause")
    // user:“PIP 时 Activity 是 paused，wry 会 webView.onPause()，必须在回调里手动
    // webView.onResume()，否则小窗是静止画面”+(所以暂停之后补一次 resume：小窗里画面必须动)。
    if (isInSmallWindow()) {
      resumeWebViewSoon()
    }
  }

  /**
   * Small window entered or left.
   *
   * The interface is told as well: a PiP window is a few centimetres wide and the full
   * layout (head, drawer, footer) has no room there.
   */
  override fun onPictureInPictureModeChanged(isInPictureInPictureMode: Boolean, newConfig: Configuration) {
    super.onPictureInPictureModeChanged(isInPictureInPictureMode, newConfig)
    applySmallWindowState(isInPictureInPictureMode)
  }

  /** API 24 and 25 only call the one-argument form. */
  @Deprecated("The two-argument form is used from API 26")
  override fun onPictureInPictureModeChanged(isInPictureInPictureMode: Boolean) {
    super.onPictureInPictureModeChanged(isInPictureInPictureMode)
    applySmallWindowState(isInPictureInPictureMode)
  }

  private fun applySmallWindowState(active: Boolean) {
    if (active) resumeWebViewSoon() else webView()?.onResume()
    try {
      nativePipMode(active)
    } catch (error: Throwable) {
      Log.w("SundayPip", "cannot report the small window state", error)
    }
  }

  /**
   * Enters the system small window, or brings this activity forward when it cannot.
   *
   * user:“优先进入画中画（PiP），进不去时把 Sunday 自身切回前台”+(所以两条路径都要有：
   * 拒绝时用户必须看到「当前设备不支持小窗」，而不是一个没有任何反应的按钮)。
   */
  @Suppress("DEPRECATION")
  fun enterSmallWindow(): Boolean {
    val supported = Build.VERSION.SDK_INT >= Build.VERSION_CODES.N &&
      packageManager.hasSystemFeature(PackageManager.FEATURE_PICTURE_IN_PICTURE)
    if (!supported) return fallbackToForeground()
    val entered = try {
      enterSmallWindowNow()
    } catch (error: Throwable) {
      Log.w("SundayPip", "cannot enter the small window", error)
      false
    }
    if (entered) return true
    return fallbackToForeground()
  }

  /**
   * The platform call itself, with an explicit `Boolean` result.
   *
   * API 26+ answers whether the transition started; the deprecated call on 24/25 returns
   * nothing at all, so it is followed by `true` and the interface learns the real outcome
   * from [onPictureInPictureModeChanged].
   */
  @Suppress("DEPRECATION")
  private fun enterSmallWindowNow(): Boolean {
    return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      enterPictureInPictureMode(PictureInPictureParams.Builder().setAspectRatio(Rational(3, 4)).build())
    } else {
      enterPictureInPictureMode()
      true
    }
  }

  private fun fallbackToForeground(): Boolean {
    // user:“进不去时把 Sunday 自身切回前台”+(回落必须看得见：一句 Toast 加一次前置)。
    Toast.makeText(this, "当前设备不支持小窗，已切回 Sunday", Toast.LENGTH_SHORT).show()
    try {
      startActivity(
        Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT),
      )
    } catch (error: Throwable) {
      Log.w("SundayPip", "cannot bring the activity forward", error)
    }
    return false
  }

  private fun isInSmallWindow(): Boolean =
    Build.VERSION.SDK_INT >= Build.VERSION_CODES.N && isInPictureInPictureMode

  /**
   * Resumes the webview after the window has settled.
   *
   * Immediately after losing focus, wry pauses the webview again during its own lifecycle
   * pass; a single synchronous `onResume` would be overwritten by that.
   */
  private fun resumeWebViewSoon() {
    val web = webView() ?: return
    web.postDelayed({ web.onResume() }, 350)
  }

  /** Keeps the window and the webview on the boot screen's own colour, never white. */
  private fun paintBootSurface() {
    val surface = try {
      Color.parseColor(BOOT_SURFACE)
    } catch (error: Throwable) {
      return
    }
    try {
      window?.setBackgroundDrawable(ColorDrawable(surface))
    } catch (error: Throwable) {
      Log.w("SundayBoot", "cannot paint the window background", error)
    }
    val paint = Runnable { webView()?.setBackgroundColor(surface) }
    paint.run()
    // wry attaches the webview during its own onCreate pass; the posted call catches it.
    window?.decorView?.post(paint)
  }

  /** The only WebView in this window is the interface; wry puts it in the content view. */
  private fun webView(): WebView? = findViewById<View>(android.R.id.content)?.let { findWebView(it) }

  private fun findWebView(view: View): WebView? {
    if (view is WebView) return view
    if (view is ViewGroup) {
      for (index in 0 until view.childCount) {
        findWebView(view.getChildAt(index))?.let { return it }
      }
    }
    return null
  }

  /**
   * No longer visible. This is the event that means background, and it is the only
   * one that is reported as such. A running turn is not cancelled here: Android kills
   * the process when it actually needs the memory, and the core journals turns so a
   * restarted app can report what was interrupted.
   */
  override fun onStop() {
    super.onStop()
    LifecycleBridge.signal("stop")
  }

  /** Visible again, in this process or in a new one. */
  override fun onResume() {
    super.onResume()
    LifecycleBridge.signal("resume")
    // user:“回到应用在 onResume 重查并 emit overlay-permission，界面据此刷新状态”+
    // (权限是在系统设置里改的，只有回到前台才知道结果；服务死没死也一起报)。
    OverlayBridge.reportState()
  }
}
