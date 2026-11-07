package com.lamtools.sunday.core

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.IBinder
import android.provider.Settings
import android.util.Log
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import android.widget.Toast
import kotlin.math.abs

/**
 * 手机悬浮环：常驻悬浮按钮 + 操作态 + 任意处长按浮出 Pin 环。
 *
 * user:“手机悬浮环：可拖动的悬浮按钮 + 操作态 + 任意处长按浮出 Pin 环 + 滑动选择 + 扇区
 * 动作落地”+(按钮和环都是独立的系统窗口：内容视图整个被 WebView 占着，往 content 里加
 * 只会被 WebView 盖住，或者盖住 WebView)。
 *
 * user:“服务要能被系统杀掉后恢复：在 onDestroy 记录偏好；下次 App 启动时如果用户开着开关，
 * 提示需要重新开启（不要静默失败）”+(所以服务是 START_NOT_STICKY：被系统杀掉后不自己
 * 复活，偏好保留成「用户想要」，界面下次进来看到 running=false 就明说需要重新开启)。
 */
class SundayOverlayService : Service() {

  companion object {
    private const val TAG = "SundayOverlay"
    private const val CHANNEL_ID = "sunday-overlay"
    private const val NOTIFICATION_ID = 4711
    private const val ACTION_START = "com.lamtools.sunday.core.overlay.START"
    private const val PREFS = "sunday-overlay"
    private const val KEY_WANTED = "wanted"

    /** 屏幕上现在有没有悬浮按钮。 */
    @Volatile
    var running: Boolean = false
      private set

    /** 用户是不是希望它开着（与服务是否活着无关，被系统杀掉后仍然为 true）。 */
    fun wanted(context: Context): Boolean =
      context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY_WANTED, false)

    private fun setWanted(context: Context, value: Boolean) {
      context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(KEY_WANTED, value).apply()
    }

    fun start(context: Context) {
      setWanted(context, true)
      val intent = Intent(context, SundayOverlayService::class.java).setAction(ACTION_START)
      try {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(intent)
        else context.startService(intent)
      } catch (error: Throwable) {
        Log.w(TAG, "cannot start the overlay service", error)
        Toast.makeText(context, "悬浮环启动失败", Toast.LENGTH_SHORT).show()
      }
    }

    fun stop(context: Context) {
      setWanted(context, false)
      context.stopService(Intent(context, SundayOverlayService::class.java))
    }
  }

  private lateinit var windowManager: WindowManager
  private var buttonView: TextView? = null
  private var buttonParams: WindowManager.LayoutParams? = null
  private var ringView: OverlayRingView? = null
  private var operationActive = false

  private var downRawX = 0f
  private var downRawY = 0f
  private var startX = 0
  private var startY = 0
  private var dragging = false

  private val density: Float
    get() = resources.displayMetrics.density

  override fun onBind(intent: Intent?): IBinder? = null

  override fun onCreate() {
    super.onCreate()
    windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager
  }

  override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    // The system gives a foreground service five seconds to call startForeground; do it
    // before the permission check so a revoked permission cannot turn into a crash.
    startAsForeground()
    if (!canDrawOverlays()) {
      // 权限被撤销过：不能什么都不做地退出，否则用户只看到开关开着而屏幕上没有环。
      Log.w(TAG, "overlay permission is missing")
      Toast.makeText(this, "悬浮环需要「显示在其他应用上层」权限", Toast.LENGTH_LONG).show()
      setWanted(this, false)
      stopSelf()
      return START_NOT_STICKY
    }
    if (buttonView == null) addButton()
    running = true
    return START_NOT_STICKY
  }

  override fun onDestroy() {
    stopOperation()
    removeButton()
    running = false
    super.onDestroy()
  }

  // ------------------------------------------------------------------ 权限与通知

  private fun canDrawOverlays(): Boolean =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) Settings.canDrawOverlays(this) else true

  private fun startAsForeground() {
    val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && manager.getNotificationChannel(CHANNEL_ID) == null) {
      manager.createNotificationChannel(
        NotificationChannel(CHANNEL_ID, "悬浮环", NotificationManager.IMPORTANCE_LOW).apply {
          description = "手机悬浮环常驻运行"
          setShowBadge(false)
        },
      )
    }
    val notification = notificationBuilder()
      .setContentTitle("悬浮环")
      .setContentText("长按屏幕任意位置打开 Pin 环")
      // A system icon keeps this feature from depending on a drawable resource, which the
      // generated project does not carry for us.
      .setSmallIcon(android.R.drawable.ic_menu_compass)
      .setOngoing(true)
      .setContentIntent(openAppIntent())
      .build()
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
      startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
    } else {
      startForeground(NOTIFICATION_ID, notification)
    }
  }

  private fun notificationBuilder(): Notification.Builder =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      Notification.Builder(this, CHANNEL_ID)
    } else {
      deprecatedNotificationBuilder()
    }

  @Suppress("DEPRECATION")
  private fun deprecatedNotificationBuilder(): Notification.Builder = Notification.Builder(this)

  private fun openAppIntent(): PendingIntent {
    val intent = Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
      PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
    } else {
      PendingIntent.FLAG_UPDATE_CURRENT
    }
    return PendingIntent.getActivity(this, 0, intent, flags)
  }

  // ------------------------------------------------------------------ 悬浮按钮

  private fun addButton() {
    val view = TextView(this).apply {
      text = "◎"
      setTextColor(Color.WHITE)
      textSize = 20f
      gravity = Gravity.CENTER
      background = circleBackground(false)
    }
    val size = dp(44)
    val params = overlayParams(size, size)
    params.x = screenWidth() - size - dp(10)
    params.y = screenHeight() / 2
    view.setOnTouchListener(dragListener)
    try {
      windowManager.addView(view, params)
      buttonView = view
      buttonParams = params
    } catch (error: Throwable) {
      Log.w(TAG, "cannot add the floating button", error)
      Toast.makeText(this, "悬浮环无法显示", Toast.LENGTH_SHORT).show()
      stopSelf()
    }
  }

  private fun removeButton() {
    val view = buttonView ?: return
    buttonView = null
    buttonParams = null
    try {
      windowManager.removeView(view)
    } catch (error: Throwable) {
      Log.w(TAG, "cannot remove the floating button", error)
    }
  }

  private val dragListener = View.OnTouchListener { view, event ->
    val params = buttonParams ?: return@OnTouchListener false
    Log.d(TAG, "button touch ${event.actionMasked} at ${event.rawX},${event.rawY}")
    when (event.actionMasked) {
      MotionEvent.ACTION_DOWN -> {
        downRawX = event.rawX
        downRawY = event.rawY
        startX = params.x
        startY = params.y
        dragging = false
        true
      }

      MotionEvent.ACTION_MOVE -> {
        val dx = (event.rawX - downRawX).toInt()
        val dy = (event.rawY - downRawY).toInt()
        // 44dp 的圆点用手指按下去本来就会抖几个像素，不算拖动。
        if (!dragging && (abs(dx) > dp(6) || abs(dy) > dp(6))) dragging = true
        if (dragging) {
          params.x = (startX + dx).coerceIn(0, maxButtonX(params.width))
          params.y = (startY + dy).coerceIn(0, maxButtonY(params.height))
          try {
            windowManager.updateViewLayout(view, params)
          } catch (error: Throwable) {
            Log.w(TAG, "cannot move the floating button", error)
          }
        }
        true
      }

      MotionEvent.ACTION_UP -> {
        if (dragging) snapToEdge(params) else toggleOperation()
        true
      }

      else -> false
    }
  }

  /** 松手吸附到最近的左右边缘：屏幕中间停一个按钮会挡住内容。 */
  private fun snapToEdge(params: WindowManager.LayoutParams) {
    val view = buttonView ?: return
    params.x = if (params.x + params.width / 2 < screenWidth() / 2) dp(10) else maxButtonX(params.width)
    try {
      windowManager.updateViewLayout(view, params)
    } catch (error: Throwable) {
      Log.w(TAG, "cannot snap the floating button", error)
    }
  }

  // ------------------------------------------------------------------ 操作态与环

  private fun toggleOperation() {
    Log.d(TAG, "toggle operation, active=$operationActive")
    if (operationActive) stopOperation() else startOperation()
  }

  private fun startOperation() {
    if (operationActive) return
    operationActive = true
    buttonView?.let { view ->
      view.text = "◉"
      view.background = circleBackground(true)
    }
    val ring = OverlayRingView(
      this,
      readOverlayRingConfig(this),
      onSector = { sector -> commit(sector) },
      onDismiss = { stopOperation() },
      onTapOutside = { stopOperation() },
    )
    val params = overlayParams(WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT)
    // 全屏透明层只收触摸，不抢焦点，所以不会弹出输入法，也不会盖掉系统的返回手势区之外的东西。
    params.flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
      WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
    params.format = PixelFormat.TRANSLUCENT
    try {
      windowManager.addView(ring, params)
      ringView = ring
      Log.d(TAG, "operation layer added, sectors=${readOverlayRingConfig(this).sectors.size}")
    } catch (error: Throwable) {
      Log.w(TAG, "cannot add the ring layer", error)
      stopOperation()
    }
  }

  private fun stopOperation() {
    operationActive = false
    val view = ringView
    ringView = null
    if (view != null) {
      try {
        windowManager.removeView(view)
      } catch (error: Throwable) {
        Log.w(TAG, "cannot remove the ring layer", error)
      }
    }
    buttonView?.let { button ->
      button.text = "◎"
      button.background = circleBackground(false)
    }
  }

  /**
   * 扇区动作落地（v1 范围）。
   *
   * user:“question / note / exclamation：把 Sunday 拉到前台，并把动作和提示词前缀交给界面，
   * 界面把文字填进输入框（不自动发送）…select：Toast「手机暂不支持框选」，不静默”+
   * (手机上没有标注画布，框选只能是明确的「不支持」，不能假装执行成功)。
   */
  private fun commit(sector: OverlaySector) {
    // 先把覆盖层收掉再拉应用，否则环会短暂盖在 Sunday 自己的界面上。
    stopOperation()
    when (sector.kind) {
      "question", "exclamation", "note" ->
        OverlayBridge.deliver(sector.kind, sector.prompt ?: defaultPrompt(sector.kind))
      "chat" -> OverlayBridge.deliver("chat", "")
      "switch" -> OverlayBridge.deliver("switch", "")
      "select" -> toast("手机暂不支持框选")
      "subring" -> toast("手机上暂未支持子环")
      else -> toast("该扇区在手机上暂未支持")
    }
  }

  private fun defaultPrompt(kind: String): String = when (kind) {
    "question" -> "？"
    "exclamation" -> "！"
    "note" -> "记录"
    else -> ""
  }

  private fun toast(message: String) {
    Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
  }

  // ------------------------------------------------------------------ 窗口工具

  @Suppress("DEPRECATION")
  private fun overlayParams(width: Int, height: Int): WindowManager.LayoutParams {
    val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
    } else {
      // API 24/25 only know TYPE_PHONE; TYPE_APPLICATION_OVERLAY arrived in 26.
      WindowManager.LayoutParams.TYPE_PHONE
    }
    return WindowManager.LayoutParams(
      width,
      height,
      type,
      WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
      PixelFormat.TRANSLUCENT,
    ).apply {
      gravity = Gravity.TOP or Gravity.START
    }
  }

  private fun circleBackground(active: Boolean): GradientDrawable = GradientDrawable().apply {
    shape = GradientDrawable.OVAL
    setColor(if (active) 0xE6357AE6.toInt() else 0xCC1B2230.toInt())
    setStroke(dp(1), if (active) 0x99FFFFFF.toInt() else 0x66FFFFFF.toInt())
  }

  private fun screenWidth(): Int = resources.displayMetrics.widthPixels

  private fun screenHeight(): Int = resources.displayMetrics.heightPixels

  private fun maxButtonX(width: Int): Int = (screenWidth() - width - dp(10)).coerceAtLeast(0)

  // Leaves room for the navigation bar or gesture area: a bubble tucked under it cannot
  // be grabbed back.
  private fun maxButtonY(height: Int): Int = (screenHeight() - height - dp(10) - dp(48)).coerceAtLeast(0)

  private fun dp(value: Int): Int = (value * density).toInt()
}
