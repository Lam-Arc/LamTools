package com.lamtools.sunday.core

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import org.json.JSONArray
import org.json.JSONObject

/**
 * 通知读取。
 *
 * user:“读取能力加上”+(短信验证码、平台提示都会出现在通知里；让模型自己读通知，而不是我们
 * 替它写一套验证码解析。这里只保留最近若干条，交给工具按需读取)。
 *
 * 需要用户在「通知使用权」里打开一次；没打开时 [connected] 为 false，工具会如实说明。
 */
class SundayNotificationListenerService : NotificationListenerService() {

  companion object {
    private const val LIMIT = 40
    private val lock = Any()
    private val recent = ArrayDeque<JSONObject>()

    @Volatile
    private var current: SundayNotificationListenerService? = null

    fun connected(): Boolean = current != null

    fun recentJson(limit: Int): String {
      val take = if (limit > 0) limit else 20
      val items = JSONArray()
      synchronized(lock) {
        for (item in recent.takeLast(take)) items.put(item)
      }
      return JSONObject()
        .put("ok", true)
        .put("result", JSONObject().put("notifications", items).put("connected", connected()))
        .toString()
    }

    private fun record(notification: StatusBarNotification) {
      val extras = notification.notification.extras ?: return
      val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()?.take(120) ?: ""
      val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()?.take(240) ?: ""
      val big = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()?.take(400) ?: ""
      val body = if (big.isNotEmpty()) big else text
      if (title.isEmpty() && body.isEmpty()) return
      val item = JSONObject()
        .put("package", notification.packageName ?: "")
        .put("title", title)
        .put("text", body)
        .put("posted_at", notification.postTime)
      synchronized(lock) {
        // 同一条通知更新时覆盖旧的那条，避免列表被同一个聊天刷屏。
        val existing = recent.indexOfFirst {
          it.optString("package") == item.optString("package") &&
            it.optString("title") == item.optString("title")
        }
        if (existing >= 0) recent.removeAt(existing)
        recent.addLast(item)
        while (recent.size > LIMIT) recent.removeFirst()
      }
    }
  }

  override fun onListenerConnected() {
    current = this
  }

  override fun onListenerDisconnected() {
    if (current === this) current = null
  }

  override fun onNotificationPosted(sbn: StatusBarNotification?) {
    if (sbn == null) return
    try {
      record(sbn)
    } catch (error: Throwable) {
      // 一条通知解析失败不该拖垮整个监听。
    }
  }
}
