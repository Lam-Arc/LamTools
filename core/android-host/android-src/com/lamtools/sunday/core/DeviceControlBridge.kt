package com.lamtools.sunday.core

import android.content.Context
import org.json.JSONObject

/**
 * Rust 与无障碍服务之间的唯一入口。
 *
 * user:“加，安卓控制，上模拟器里把它跑通”+(宿主从 Core 收到一个 JSON 请求，转给这里；
 * 服务没开就如实说没开，不要让模型看到一个空界面还以为点成功了)。
 *
 * Rust 通过 `call_static_method` 调这两个方法，签名必须和 `device_control.rs` 完全一致；
 * 改了名字或参数要两边一起改，否则第一次调用就是 NoSuchMethodError。
 */
object DeviceControlBridge {

  @Volatile
  private var appContext: Context? = null

  fun attach(context: Context) {
    appContext = context.applicationContext
  }

  /** 当前是否已经拿到无障碍服务；给工具的自检用。 */
  @JvmStatic
  fun status(): String {
    val service = SundayAccessibilityService.service()
    return JSONObject()
      .put("ok", true)
      .put("connected", service != null)
      .put("package", appContext?.packageName ?: "")
      .toString()
  }

  /** 一个请求做一个动作，返回 `{"ok":bool,"result":{...}}` 或 `{"ok":false,"error":"..."}`。 */
  @JvmStatic
  fun action(request: String): String {
    // user:“读取能力加上”+(通知和无障碍是两套系统授权：无障碍没开不该连通知一起读不到，
    // 所以 notifications 直接走监听服务，不经过无障碍)。
    val parsed = try {
      JSONObject(request)
    } catch (error: Exception) {
      null
    }
    if (parsed?.optString("action") == "notifications") {
      return SundayNotificationListenerService.recentJson(parsed.optInt("limit", 20))
    }
    val service = SundayAccessibilityService.service()
      ?: return JSONObject()
        .put("ok", false)
        .put("error", "无障碍服务没有开启：在系统设置 → 无障碍里打开 Sunday 的设备控制")
        .toString()
    return try {
      service.performJson(request)
    } catch (error: Throwable) {
      JSONObject()
        .put("ok", false)
        .put("error", "执行失败：${error.message ?: error.javaClass.simpleName}")
        .toString()
    }
  }
}
