package com.lamtools.sunday.core

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.view.MotionEvent
import android.view.View
import org.json.JSONObject
import java.io.File
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.hypot
import kotlin.math.sin

/**
 * 一个扇区：桌面 Ping 环配置里的一项，手机只读不改。
 *
 * 字段与 `core/ui/src/pet/config.ts` 的 `PingSectorConfig` 逐项对应，因为配置就是同一份
 * JSON 文件，手机上不能再发明第二套含义。
 */
data class OverlaySector(
  val id: String,
  val label: String,
  val icon: String,
  val kind: String,
  val color: String,
  val prompt: String?,
)

data class OverlayRingConfig(
  val radiusDp: Float,
  val ringWidthDp: Float,
  val sectors: List<OverlaySector>,
)

// user:“读不到或解析失败就用内置默认值（提问/注意/记录/对话/切换会话），并且不要崩”+
// (所以默认值写在这里：没有桌面配置的手机也必须能开环)。
private val DEFAULT_SECTORS = listOf(
  OverlaySector("question", "提问", "?", "question", "#6AA8FF", "？"),
  OverlaySector("exclamation", "注意", "!", "exclamation", "#FF9F5A", "！"),
  OverlaySector("note", "记录", "记", "note", "#7ED6A5", "记录"),
  OverlaySector("chat", "对话", "聊", "chat", "#8FD6FF", null),
  OverlaySector("switch", "切换会话", "⇄", "switch", "#BFC7D5", null),
)

private val DEFAULT_CONFIG = OverlayRingConfig(112f, 14f, DEFAULT_SECTORS)

/**
 * 读桌宠配置里的 `ping` 段。
 *
 * user:“配置来源：读 <filesDir>/runtime/userdata/.lam/pet/config.json 的 ping 段
 * （radius、ringWidth、sectors 的 id/label/icon/color/kind/enabled/group）”+
 * (手机端只读根环：没有 group 的启用项；子环项在这一版不画，选了会明说暂不支持)。
 */
fun readOverlayRingConfig(context: Context): OverlayRingConfig {
  val file = File(File(File(File(context.filesDir, "runtime"), "userdata"), ".lam"), "pet/config.json")
  val text = try {
    if (file.isFile) file.readText() else return DEFAULT_CONFIG
  } catch (error: Throwable) {
    return DEFAULT_CONFIG
  }
  val ping = try {
    JSONObject(text).optJSONObject("ping")
  } catch (error: Throwable) {
    null
  } ?: return DEFAULT_CONFIG

  // 配置里的 radius/ringWidth 是按桌面窗口像素写的；手机按 dp 解释并夹到能放进屏幕的范围，
  // 否则一个 132 的默认半径在 392dp 宽的屏幕上整圈会被切掉。
  val radius = ping.optDouble("radius", DEFAULT_CONFIG.radiusDp.toDouble()).toFloat().coerceIn(70f, 118f)
  val ringWidth = ping.optDouble("ringWidth", DEFAULT_CONFIG.ringWidthDp.toDouble()).toFloat().coerceIn(8f, 26f)

  val array = ping.optJSONArray("sectors") ?: return OverlayRingConfig(radius, ringWidth, DEFAULT_SECTORS)
  val sectors = ArrayList<OverlaySector>()
  for (index in 0 until array.length()) {
    val item = array.optJSONObject(index) ?: continue
    if (!item.optBoolean("enabled", true)) continue
    // v1 只画根环：属于某个子轮盘的项在这里不可达。
    if (item.optString("group").isNotEmpty()) continue
    sectors.add(
      OverlaySector(
        id = item.optString("id"),
        label = item.optString("label"),
        icon = item.optString("icon"),
        kind = item.optString("kind"),
        color = item.optString("color", "#6AA8FF"),
        prompt = item.optString("prompt").ifEmpty { null },
      ),
    )
  }
  if (sectors.isEmpty()) return OverlayRingConfig(radius, ringWidth, DEFAULT_SECTORS)
  return OverlayRingConfig(radius, ringWidth, sectors)
}

/**
 * 全屏透明的操作层：长按浮出环、移动高亮、松手执行。
 *
 * user:“长按判定 450ms 且移动小于 12dp。长按点在屏幕任意位置都可以，环以该点为圆心弹出”+
 * (所以这个 View 同时负责手势与绘制：多开一个窗口就会多一层抢触摸的风险)。
 *
 * 几何与桌面完全一致，直接照 `core/ui/src/pet/ping/ringModel.ts` 的 `sectorIndexAt`：
 * 死区 0.35、角度从正上方开始顺时针、超出 `radius + ringWidth * 2` 视为环外。
 */
class OverlayRingView(
  context: Context,
  private val config: OverlayRingConfig,
  private val onSector: (OverlaySector) -> Unit,
  private val onDismiss: () -> Unit,
  private val onTapOutside: () -> Unit,
) : View(context) {

  private val density = resources.displayMetrics.density
  private val longPressDelay = 450L
  private val moveSlop = 12f * density
  private val ringExpiryMs = 6000L

  private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG)
  private val hubPaint = Paint(Paint.ANTI_ALIAS_FLAG)
  private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    textAlign = Paint.Align.CENTER
    typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
  }

  private var ringVisible = false
  private var centerX = 0f
  private var centerY = 0f
  private var highlighted = -1
  private var downX = 0f
  private var downY = 0f

  private val showRing = Runnable { show() }
  private val expireRing = Runnable { cancel("timeout") }

  private fun show() {
    if (ringVisible) return
    ringVisible = true
    centerX = downX
    centerY = downY
    highlighted = -1
    invalidate()
    removeCallbacks(expireRing)
    postDelayed(expireRing, ringExpiryMs)
  }

  /** 收起环并退出操作态。`reason` 只用于日志可读性。 */
  private fun cancel(reason: String) {
    removeCallbacks(showRing)
    removeCallbacks(expireRing)
    val wasVisible = ringVisible
    ringVisible = false
    highlighted = -1
    if (wasVisible) invalidate()
    onDismiss()
  }

  private fun sectorAt(dx: Float, dy: Float): Int {
    val count = config.sectors.size
    if (count <= 0) return -1
    val radius = config.radiusDp * density
    val ringWidth = config.ringWidthDp * density
    val distance = hypot(dx, dy)
    if (distance > radius + ringWidth * 2) return -1
    if (distance < radius * 0.35f) return -1
    var angle = atan2(dy, dx) + (Math.PI / 2).toFloat()
    if (angle < 0f) angle += (Math.PI * 2).toFloat()
    val step = (Math.PI * 2).toFloat() / count
    return floor(angle / step).toInt() % count
  }

  override fun onTouchEvent(event: MotionEvent): Boolean {
    when (event.actionMasked) {
      MotionEvent.ACTION_DOWN -> {
        downX = event.x
        downY = event.y
        // 环已经浮出时不重新计时：第二根手指只是继续选方向。
        if (!ringVisible) {
          removeCallbacks(showRing)
          removeCallbacks(expireRing)
          postDelayed(showRing, longPressDelay)
        }
        return true
      }

      MotionEvent.ACTION_MOVE -> {
        if (ringVisible) {
          val index = sectorAt(event.x - centerX, event.y - centerY)
          if (index != highlighted) {
            highlighted = index
            invalidate()
          }
        } else if (hypot(event.x - downX, event.y - downY) > moveSlop) {
          // 划动而不是长按：这一次不算开环。
          removeCallbacks(showRing)
        }
        return true
      }

      MotionEvent.ACTION_UP -> {
        removeCallbacks(showRing)
        if (ringVisible) {
          val index = sectorAt(event.x - centerX, event.y - centerY)
          removeCallbacks(expireRing)
          ringVisible = false
          highlighted = -1
          invalidate()
          if (index >= 0) onSector(config.sectors[index]) else onDismiss()
        } else {
          // 操作态里轻点一下就是取消。
          onTapOutside()
        }
        return true
      }

      MotionEvent.ACTION_CANCEL -> {
        cancel("cancelled")
        return true
      }
    }
    return true
  }

  override fun onDraw(canvas: Canvas) {
    super.onDraw(canvas)
    if (!ringVisible) return
    val count = config.sectors.size
    if (count <= 0) return

    val radius = config.radiusDp * density
    val ringWidth = config.ringWidthDp * density
    val band = radius + ringWidth / 2f
    val step = 360f / count

    for (index in 0 until count) {
      val start = index * step - 90f
      val color = parseColor(config.sectors[index].color)
      ringPaint.style = Paint.Style.STROKE
      ringPaint.strokeWidth = if (index == highlighted) ringWidth * 1.6f else ringWidth
      ringPaint.color = if (index == highlighted) brighten(color) else dim(color)
      canvas.drawArc(
        centerX - band,
        centerY - band,
        centerX + band,
        centerY + band,
        start,
        step - 1.5f,
        false,
        ringPaint,
      )
    }

    // 中心盘：死区那里不选任何扇区，所以直接拿它当「松开执行」的提示位。
    val hub = radius * 0.35f
    hubPaint.style = Paint.Style.FILL
    hubPaint.color = 0xE610151C.toInt()
    canvas.drawCircle(centerX, centerY, hub, hubPaint)
    hubPaint.style = Paint.Style.STROKE
    hubPaint.strokeWidth = 1.5f * density
    hubPaint.color = 0x66FFFFFF
    canvas.drawCircle(centerX, centerY, hub, hubPaint)

    textPaint.color = 0xE6FFFFFF.toInt()
    textPaint.textSize = 12f * resources.displayMetrics.scaledDensity
    drawCentered(canvas, "松开执行", centerX, centerY)

    for (index in 0 until count) {
      val sector = config.sectors[index]
      val angle = Math.toRadians((index * step + step / 2f - 90f).toDouble())
      val x = centerX + cos(angle).toFloat() * band
      val y = centerY + sin(angle).toFloat() * band
      val highlightedNow = index == highlighted
      textPaint.textSize = (if (highlightedNow) 19f else 15f) * resources.displayMetrics.scaledDensity
      textPaint.color = if (highlightedNow) Color.WHITE else 0xD9FFFFFF.toInt()
      val mark = sector.icon.ifEmpty { sector.label.take(1) }
      drawCentered(canvas, mark, x, y)
    }
  }

  private fun drawCentered(canvas: Canvas, text: String, x: Float, y: Float) {
    if (text.isEmpty()) return
    val baseline = y - (textPaint.ascent() + textPaint.descent()) / 2f
    canvas.drawText(text, x, baseline, textPaint)
  }

  private fun parseColor(value: String): Int = try {
    Color.parseColor(value)
  } catch (error: Throwable) {
    0xFF6AA8FF.toInt()
  }

  private fun dim(color: Int): Int = Color.argb(150, Color.red(color), Color.green(color), Color.blue(color))

  private fun brighten(color: Int): Int = Color.rgb(
    (Color.red(color) + (255 - Color.red(color)) * 0.35f).toInt(),
    (Color.green(color) + (255 - Color.green(color)) * 0.35f).toInt(),
    (Color.blue(color) + (255 - Color.blue(color)) * 0.35f).toInt(),
  )
}
