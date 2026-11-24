package com.lamtools.sunday.core

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log

/**
 * Keeps the app process alive while the phone is away from the screen.
 *
 * user:“优先保证连接的稳定，减少无故断连或者无连接反馈的情况”+(Android 会把后台进程
 * 冻结/回收，隧道再稳也会被系统掐断。这里只做一件事：用一条低优先级通知把进程留在
 * 前台服务里；连接本身仍然由 Rust 宿主与 `sunday-p2p` 负责)。
 *
 * user:“简单可靠易用”+(所以没有第二个连接实现、没有账号，也没有常驻轮询；用户关掉
 * 「后台保持连接」就停止服务，下次启动也不会自己回来)。
 */
class SundayConnectionService : Service() {

  companion object {
    private const val TAG = "SundayConnection"
    private const val CHANNEL_ID = "sunday-connection"
    private const val NOTIFICATION_ID = 4712
    private const val PREFS = "sunday-connection"
    private const val KEY_WANTED = "wanted"

    /** 服务是否真的在跑（被系统杀掉后为 false，偏好仍然保留）。 */
    @Volatile
    var running: Boolean = false
      private set

    /** 用户是否希望后台保持连接。 */
    fun wanted(context: Context): Boolean =
      context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY_WANTED, false)

    private fun setWanted(context: Context, value: Boolean) {
      context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .edit().putBoolean(KEY_WANTED, value).apply()
    }

    fun start(context: Context) {
      setWanted(context, true)
      val intent = Intent(context, SundayConnectionService::class.java)
      try {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
          context.startForegroundService(intent)
        } else {
          context.startService(intent)
        }
      } catch (error: Throwable) {
        // A denied background start is not fatal: the app is still usable while it is
        // visible, and the next foreground attach retries.
        Log.w(TAG, "cannot start the connection service", error)
      }
    }

    fun stop(context: Context) {
      setWanted(context, false)
      context.stopService(Intent(context, SundayConnectionService::class.java))
    }
  }

  override fun onBind(intent: Intent?): IBinder? = null

  override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    startAsForeground()
    running = true
    return START_NOT_STICKY
  }

  override fun onDestroy() {
    running = false
    super.onDestroy()
  }

  private fun startAsForeground() {
    val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && manager.getNotificationChannel(CHANNEL_ID) == null) {
      manager.createNotificationChannel(
        NotificationChannel(CHANNEL_ID, "后台连接", NotificationManager.IMPORTANCE_LOW).apply {
          description = "保持手机与电脑的连接"
          setShowBadge(false)
        },
      )
    }
    val notification = notificationBuilder()
      .setContentTitle("Sunday")
      .setContentText("正在后台保持与电脑的连接")
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
}
