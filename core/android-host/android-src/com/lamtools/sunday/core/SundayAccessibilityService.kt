package com.lamtools.sunday.core

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Path
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.util.Base64
import android.view.Display
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * 安卓设备控制：读屏与手势。
 *
 * user:“加，安卓控制，上模拟器里把它跑通”+(让 Sunday 自己看手机界面、点按、滑动、输入、
 * 返回桌面、打开应用。读屏和手势都走系统的无障碍服务，不 root、不 adb)。
 *
 * 它只负责「看」和「做」，不认识对话、审批或模型；所有动作由 [DeviceControlBridge] 转成
 * JSON 交给 Rust，再由 Core 的 android_use 工具交给模型。
 */
class SundayAccessibilityService : AccessibilityService() {

  companion object {
    private const val TAG = "SundayA11y"

    @Volatile
    private var current: SundayAccessibilityService? = null

    fun connected(): Boolean = current != null

    fun service(): SundayAccessibilityService? = current
  }

  override fun onServiceConnected() {
    current = this
    Log.i(TAG, "accessibility service connected")
  }

  override fun onDestroy() {
    if (current === this) current = null
    Log.i(TAG, "accessibility service destroyed")
    super.onDestroy()
  }

  override fun onInterrupt() {}

  override fun onAccessibilityEvent(event: AccessibilityEvent?) {}

  // ---------------------------------------------------------------------------
  // 读屏
  // ---------------------------------------------------------------------------

  fun snapshotJson(maxNodes: Int): String {
    val root = rootInActiveWindow ?: return errorJson("当前没有可读的界面")
    val nodes = JSONArray()
    var count = 0

    fun walk(node: AccessibilityNodeInfo, path: String, depth: Int) {
      if (count >= maxNodes || depth > 30) return
      nodes.put(nodeJson(node, path))
      count += 1
      if (count >= maxNodes) return
      for (index in 0 until node.childCount) {
        val child = node.getChild(index) ?: continue
        walk(child, "$path.$index", depth + 1)
        if (count >= maxNodes) return
      }
    }

    walk(root, "0", 0)
    val metrics = resources.displayMetrics
    val payload = JSONObject()
      .put("package", root.packageName?.toString() ?: "")
      .put("screen", JSONArray().put(metrics.widthPixels).put(metrics.heightPixels))
      .put("nodes", nodes)
      .put("truncated", count >= maxNodes)
    return okJson(payload)
  }

  private fun nodeJson(node: AccessibilityNodeInfo, path: String): JSONObject {
    val bounds = Rect()
    node.getBoundsInScreen(bounds)
    val hint = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      node.hintText?.toString()?.take(120) ?: ""
    } else {
      ""
    }
    return JSONObject()
      .put("ref", path)
      .put("class", node.className?.toString()?.substringAfterLast('.') ?: "")
      .put("text", node.text?.toString()?.take(120) ?: "")
      .put("desc", node.contentDescription?.toString()?.take(120) ?: "")
      .put("hint", hint)
      .put("package", node.packageName?.toString() ?: "")
      .put("bounds", JSONArray().put(bounds.left).put(bounds.top).put(bounds.right).put(bounds.bottom))
      .put("clickable", node.isClickable)
      .put("editable", node.isEditable)
      .put("scrollable", node.isScrollable)
      .put("checked", node.isChecked)
      .put("focused", node.isFocused)
      .put("enabled", node.isEnabled)
  }

  private fun resolve(path: String): AccessibilityNodeInfo? {
    val root = rootInActiveWindow ?: return null
    val parts = path.split('.').filter { it.isNotEmpty() }
    if (parts.isEmpty() || path == "0") return root
    // snapshot 里的 ref 是 "0.2.1" 这种路径：第一段永远是根，从第二段开始才是子节点索引。
    var node = root
    val start = if (parts.first() == "0") 1 else 0
    for (index in start until parts.size) {
      val child = parts[index].toIntOrNull() ?: return null
      node = node.getChild(child) ?: return null
    }
    return node
  }

  // ---------------------------------------------------------------------------
  // 动作
  // ---------------------------------------------------------------------------

  fun performJson(request: String): String {
    val json = try {
      JSONObject(request)
    } catch (error: Exception) {
      return errorJson("请求不是合法的 JSON")
    }
    val action = json.optString("action")
    return when (action) {
      "snapshot" -> snapshotJson(json.optInt("max_nodes", 80))
      // user:“读取能力加上”+(让模型自己看屏幕，而不是我们替它写识别；截图只做缩放与压缩)。
      "screenshot" -> screenshotJson(json.optInt("max_width", 900))
      "status" -> okJson(JSONObject().put("connected", true))
      "tap" -> tap(json.optInt("x"), json.optInt("y"), 0)
      "long_press" -> tap(json.optInt("x"), json.optInt("y"), json.optLong("duration_ms", 700))
      "swipe" -> swipe(json)
      "tap_node" -> tapNode(json.optString("ref"))
      "set_text" -> setText(json.optString("ref"), json.optString("text"))
      "global" -> global(json.optString("name"))
      "open_app" -> openApp(json.optString("package"))
      "list_apps" -> listApps(json.optString("query"))
      else -> errorJson("不支持的动作：$action")
    }
  }

  private fun tap(x: Int, y: Int, longMs: Long): String {
    if (x <= 0 || y <= 0) return errorJson("坐标无效，先 snapshot 看元素位置")
    val path = Path().apply { moveTo(x.toFloat(), y.toFloat()) }
    val duration = if (longMs > 0) longMs else 60L
    return dispatch(GestureDescription.StrokeDescription(path, 0, duration))
  }

  private fun swipe(json: JSONObject): String {
    val from = json.optJSONArray("from") ?: return errorJson("swipe 需要 from")
    val to = json.optJSONArray("to") ?: return errorJson("swipe 需要 to")
    val path = Path().apply {
      moveTo(from.optDouble(0).toFloat(), from.optDouble(1).toFloat())
      lineTo(to.optDouble(0).toFloat(), to.optDouble(1).toFloat())
    }
    val duration = json.optLong("duration_ms", 300).coerceAtLeast(50)
    return dispatch(GestureDescription.StrokeDescription(path, 0, duration))
  }

  private fun tapNode(ref: String): String {
    val node = resolve(ref) ?: return errorJson("找不到这个元素：$ref")
    val bounds = Rect()
    node.getBoundsInScreen(bounds)
    // user:“加，安卓控制，上模拟器里把它跑通”+(WebView 里的输入框在 performAction(CLICK)
    // 时会抛异常（length=1; index=1），以前一次异常就把整个 tap_node 变成失败；这里按
    // 「系统动作不行就点中心」处理，不让一个实现细节挡住点击)。
    val clicked = try {
      node.isClickable && node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
    } catch (error: Throwable) {
      Log.w(TAG, "performAction(CLICK) failed on $ref", error)
      false
    }
    if (clicked) {
      return okJson(JSONObject().put("clicked", ref))
    }
    // 不可点击的容器很常见：退回到点它的中心。
    if (bounds.width() <= 0 || bounds.height() <= 0) return errorJson("这个元素没有可点的区域")
    return tap(bounds.centerX(), bounds.centerY(), 0)
  }

  private fun setText(ref: String, text: String): String {
    val node = resolve(ref) ?: return errorJson("找不到这个元素：$ref")
    // user:“加，安卓控制，上模拟器里把它跑通”+(WebView 的输入框对 ACTION_SET_TEXT 也会抛
    // 异常；一次异常不该让「写文本」这件事变成永远失败，先试系统动作，再退到聚焦后重试)。
    val args = Bundle().apply {
      putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
    }
    if (node.isEditable) {
      val written = try {
        node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
      } catch (error: Throwable) {
        Log.w(TAG, "performAction(SET_TEXT) failed on $ref", error)
        false
      }
      if (written) {
        return okJson(JSONObject().put("text", text))
      }
    }
    // 有些输入框只认粘贴：先聚焦，再用系统的“设置文本”动作。
    try {
      node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
      if (node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) {
        return okJson(JSONObject().put("text", text))
      }
    } catch (error: Throwable) {
      Log.w(TAG, "performAction(FOCUS) failed on $ref", error)
    }
    return errorJson("这个控件不接受直接写文本，先点进输入框再试，或者换一个可编辑的元素")
  }

  private fun global(name: String): String {
    val action = when (name) {
      "back" -> GLOBAL_ACTION_BACK
      "home" -> GLOBAL_ACTION_HOME
      "recents" -> GLOBAL_ACTION_RECENTS
      "notifications" -> GLOBAL_ACTION_NOTIFICATIONS
      else -> return errorJson("不认识的动作：$name，可选 back / home / recents / notifications")
    }
    return if (performGlobalAction(action)) {
      okJson(JSONObject().put("global", name))
    } else {
      errorJson("系统拒绝了这次操作")
    }
  }

  private fun openApp(packageName: String): String {
    if (packageName.isEmpty()) return errorJson("open_app 需要 package")
    val intent = packageManager.getLaunchIntentForPackage(packageName)
      ?: return errorJson("没有找到可以打开的应用：$packageName")
    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    applicationContext.startActivity(intent)
    return okJson(JSONObject().put("started", packageName))
  }

  private fun listApps(query: String): String {
    val apps = JSONArray()
    val keyword = query.trim().lowercase()
    val infos = packageManager.getInstalledApplications(PackageManager.GET_META_DATA)
    for (info in infos) {
      val launchable = packageManager.getLaunchIntentForPackage(info.packageName) != null
      if (!launchable) continue
      val label = packageManager.getApplicationLabel(info).toString()
      if (keyword.isNotEmpty() &&
        !label.lowercase().contains(keyword) &&
        !info.packageName.lowercase().contains(keyword)
      ) {
        continue
      }
      apps.put(JSONObject().put("label", label).put("package", info.packageName))
    }
    return okJson(JSONObject().put("apps", apps))
  }

  /**
   * 截一张屏幕，缩到指定宽度后压成 JPEG。
   *
   * user:“读取能力加上”+(给模型一张图，让它自己看拼图、看图片验证码、看界面画得对不对；
   * 这一层只负责取图，不做任何识别)。
   */
  private fun screenshotJson(maxWidth: Int): String {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
      return errorJson("截图需要 Android 11 及以上")
    }
    var bitmap: Bitmap? = null
    val latch = CountDownLatch(1)
    takeScreenshot(
      Display.DEFAULT_DISPLAY,
      mainExecutor,
      object : TakeScreenshotCallback {
        override fun onSuccess(result: ScreenshotResult) {
          try {
            val buffer = result.hardwareBuffer
            val wrapped = Bitmap.wrapHardwareBuffer(buffer, result.colorSpace)
            bitmap = wrapped?.copy(Bitmap.Config.ARGB_8888, false)
            buffer.close()
          } catch (error: Throwable) {
            Log.w(TAG, "screenshot copy failed", error)
            bitmap = null
          }
          latch.countDown()
        }

        override fun onFailure(errorCode: Int) {
          Log.w(TAG, "screenshot failed: $errorCode")
          latch.countDown()
        }
      },
    )
    if (!latch.await(7, TimeUnit.SECONDS)) return errorJson("截图超时")
    val shot = bitmap ?: return errorJson("截图失败，系统没有给出画面")
    val target = if (maxWidth > 0) maxWidth else 900
    val scale = minOf(1f, target.toFloat() / shot.width)
    val scaled = if (scale < 1f) {
      Bitmap.createScaledBitmap(shot, (shot.width * scale).toInt(), (shot.height * scale).toInt(), true)
    } else {
      shot
    }
    val out = ByteArrayOutputStream()
    scaled.compress(Bitmap.CompressFormat.JPEG, 82, out)
    val bytes = out.toByteArray()
    return okJson(
      JSONObject()
        .put("mime", "image/jpeg")
        .put("width", scaled.width)
        .put("height", scaled.height)
        .put("image_base64", Base64.encodeToString(bytes, Base64.NO_WRAP)),
    )
  }

  /** 执行一次手势并等它真的完成；回调走主线程，所以调用方必须在后台线程上。 */
  private fun dispatch(stroke: GestureDescription.StrokeDescription): String {
    val builder = GestureDescription.Builder()
    builder.addStroke(stroke)
    val latch = CountDownLatch(1)
    var completed = false
    val delivered = dispatchGesture(
      builder.build(),
      object : GestureResultCallback() {
        override fun onCompleted(gestureDescription: GestureDescription?) {
          completed = true
          latch.countDown()
        }

        override fun onCancelled(gestureDescription: GestureDescription?) {
          latch.countDown()
        }
      },
      null,
    )
    if (!delivered) return errorJson("系统拒绝了这次手势，确认无障碍服务还开着")
    latch.await(6, TimeUnit.SECONDS)
    return if (completed) okJson(JSONObject().put("done", true)) else errorJson("手势没有执行完成")
  }

  private fun okJson(payload: JSONObject): String =
    JSONObject().put("ok", true).put("result", payload).toString()

  private fun errorJson(message: String): String =
    JSONObject().put("ok", false).put("error", message).toString()
}
