package com.lamtools.sunday.core

import android.annotation.SuppressLint
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import org.json.JSONObject
import org.json.JSONTokener
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * The native webview layer the shared browser tab draws into.
 *
 * user:“在手机端，网页搜索时不应该去自动跳到分屏，而是收进标签页抽屉”+
 * “进来页之后要能切、能返回”+(页是界面里的一块区域，网页是这块区域里的原生 View：
 * 界面只下发矩形和可见性，网页自己负责加载、导航与取内容)。
 *
 * 约定（和桌面同一条）：矩形一律是**物理像素**，由前端乘过一次 devicePixelRatio；
 * Android 的 LayoutParams 也是物理像素，所以这里不再乘任何比例，避免 dpr² 的偏移。
 *
 * 一次只保留一张网页：手机屏幕只有一个“当前页”，关页即销毁，避免后台网页继续占内存。
 */
object BrowserBridge {
  private const val TAG = "SundayBrowser"

  private val main = Handler(Looper.getMainLooper())
  private val views = LinkedHashMap<String, WebView>()
  private var container: FrameLayout? = null
  private var nextId = 1

  init {
    System.loadLibrary("sunday_android_host_lib")
    nativeRegister()
  }

  /** Rust's way back into this object. */
  @JvmStatic external fun nativeRegister()

  /** Called once from `MainActivity.onCreate` so the init block (and native registration) runs. */
  @JvmStatic
  fun prepare() {
    ensureContainer()
  }

  /** Runs `block` on the UI thread and waits for it, whatever thread called us. */
  private fun <T> onUi(block: () -> T): T? {
    if (Looper.myLooper() == Looper.getMainLooper()) return block()
    var result: T? = null
    val latch = CountDownLatch(1)
    main.post {
      try {
        result = block()
      } catch (error: Throwable) {
        Log.w(TAG, "ui task failed", error)
      } finally {
        latch.countDown()
      }
    }
    if (!latch.await(6, TimeUnit.SECONDS)) {
      Log.w(TAG, "ui task timed out")
      return null
    }
    return result
  }

  /** The overlay host: one full-size, transparent-to-touches container inside the activity. */
  private fun ensureContainer(): FrameLayout? {
    val existing = container
    if (existing != null && existing.parent != null) return existing
    val activity = MainActivity.current() ?: return null
    val root = activity.findViewById<ViewGroup>(android.R.id.content) ?: return null
    val frame = FrameLayout(activity)
    frame.layoutParams = FrameLayout.LayoutParams(
      ViewGroup.LayoutParams.MATCH_PARENT,
      ViewGroup.LayoutParams.MATCH_PARENT,
    )
    // The container itself must not eat touches: only the webview inside it is interactive.
    frame.isClickable = false
    frame.isFocusable = false
    root.addView(frame)
    container = frame
    return frame
  }

  @SuppressLint("SetJavaScriptEnabled")
  private fun createWebView(): WebView? {
    val activity = MainActivity.current() ?: return null
    val host = ensureContainer() ?: return null
    val view = WebView(activity)
    view.settings.javaScriptEnabled = true
    view.settings.domStorageEnabled = true
    // 手机页给多少像素就画多少：宽视口 + 概览模式会让网页按桌面宽度排版，
    // 再被缩放到这块矩形里，第一次测量时甚至拿不到宽度（innerWidth=0）。
    view.settings.useWideViewPort = false
    view.settings.loadWithOverviewMode = false
    view.settings.setSupportZoom(true)
    view.settings.builtInZoomControls = false
    view.settings.setSupportMultipleWindows(false)
    view.settings.mediaPlaybackRequiresUserGesture = true
    view.setBackgroundColor(0xFFFFFFFF.toInt())
    view.webViewClient = object : WebViewClient() {
      override fun shouldOverrideUrlLoading(view: WebView, url: String): Boolean = false
    }
    // user:“修”+(统一由 MainActivity 按应用的调试标志决定是否允许 WebView 调试)。
    host.addView(
      view,
      FrameLayout.LayoutParams(0, 0).apply { leftMargin = 0; topMargin = 0 },
    )
    view.visibility = View.INVISIBLE
    return view
  }

  /** Opens one page and returns its id; an empty url leaves it blank until [navigate]. */
  @JvmStatic
  fun open(url: String): String {
    val id = "browser-" + nextId++
    onUi {
      val view = createWebView() ?: return@onUi
      views[id] = view
      if (url.isNotBlank()) view.loadUrl(url)
    }
    return id
  }

  @JvmStatic
  fun bounds(tab: String, x: Int, y: Int, width: Int, height: Int, visible: Boolean) {
    onUi {
      val view = views[tab] ?: return@onUi
      val params = view.layoutParams as FrameLayout.LayoutParams
      params.width = width.coerceAtLeast(1)
      params.height = height.coerceAtLeast(1)
      params.leftMargin = x
      params.topMargin = y
      view.layoutParams = params
      view.visibility = if (visible) View.VISIBLE else View.INVISIBLE
      // 尺寸变了要让 WebView 重新算一次视口，否则网页仍按 0 宽排版。
      view.requestLayout()
      view.invalidate()
    }
  }

  @JvmStatic
  fun navigate(tab: String, action: String, url: String) {
    onUi {
      val view = views[tab] ?: return@onUi
      when (action) {
        "navigate" -> if (url.isNotBlank()) view.loadUrl(url)
        "back" -> if (view.canGoBack()) view.goBack()
        "forward" -> if (view.canGoForward()) view.goForward()
        "reload" -> view.reload()
        "stop" -> view.stopLoading()
      }
      Unit
    }
  }

  /** 收起一张网页：只是不可见，页面状态与滚动位置都留着。 */
  @JvmStatic
  fun hide(tab: String) {
    onUi {
      views[tab]?.visibility = View.INVISIBLE
      Unit
    }
  }

  /**
   * 收起全部网页。
   *
   * user:“网页收不起来，收起来了仍出现”+(原生 View 永远压在界面之上：只要有一张没被收走，
   * 回到会话后它还会浮在上面。所以离开页面时按“全部收起”兜底，不赌某一处映射是对的)。
   */
  @JvmStatic
  fun hideAll() {
    onUi {
      for (view in views.values) view.visibility = View.INVISIBLE
      Unit
    }
  }

  @JvmStatic
  fun activate(tab: String) {
    onUi {
      views[tab]?.bringToFront()
      Unit
    }
  }

  @JvmStatic
  fun close(tab: String) {
    onUi {
      val view = views.remove(tab) ?: return@onUi
      (view.parent as? ViewGroup)?.removeView(view)
      view.stopLoading()
      view.destroy()
      Unit
    }
  }

  /** Current address, title and navigation flags — the page header and tab title read this. */
  @JvmStatic
  fun state(tab: String): String {
    val payload = JSONObject()
    onUi {
      val view = views[tab]
      if (view == null) {
        payload.put("missing", true)
        return@onUi
      }
      payload.put("url", view.url ?: "")
      payload.put("title", view.title ?: "")
      payload.put("loading", view.progress in 0..99)
      payload.put("canGoBack", view.canGoBack())
      payload.put("canGoForward", view.canGoForward())
      Unit
    }
    return payload.toString()
  }

  /**
   * Reads the page: up to `maxNodes` nodes per selector plus a prefix of visible text.
   *
   * `evaluateJavascript` answers on the UI thread, so the wait happens on this (Rust) thread
   * while the callback lands on the looper that posted it.
   */
  @JvmStatic
  fun html(
    tab: String,
    selectorsJson: String,
    maxNodes: Int,
    perNodeChars: Int,
    maxChars: Int,
    pageTextChars: Int,
  ): String {
    // user:“修”+(正文只经本次原生求值的回调返回，不向网页暴露宿主接口)。
    val timeout = """{"nodes":[],"counts":{"matched":0,"returned":0,"omitted":0,"chars":0,"truncated":false},"pageText":"","skippedSelectors":[],"timeout":true}"""
    if (Looper.myLooper() == Looper.getMainLooper()) return timeout
    val answered = CountDownLatch(1)
    var payload: String? = null
    val script = "(function(){"
      .plus("var sels=").plus(selectorsJson).plus(";")
      .plus("var maxNodes=").plus(maxNodes).plus(",perNode=").plus(perNodeChars)
      .plus(",maxChars=").plus(maxChars).plus(",pageText=").plus(pageTextChars).plus(";")
      .plus("var out=[],matched=0,omitted=0,chars=0,skipped=[];")
      .plus("for(var i=0;i<sels.length;i++){var sel=sels[i],nodes=null;")
      .plus("try{nodes=document.querySelectorAll(sel);}catch(e){skipped.push(sel);continue;}")
      .plus("matched+=nodes.length;")
      .plus("for(var j=0;j<nodes.length;j++){")
      .plus("if(out.length>=maxNodes){omitted++;continue;}")
      .plus("var html=nodes[j].outerHTML||nodes[j].textContent||'';")
      .plus("if(html.length>perNode){html=html.slice(0,perNode);}")
      .plus("if(chars+html.length>maxChars){omitted++;continue;}")
      .plus("chars+=html.length;out.push({selector:sel,html:html});}}")
      .plus("var text=pageText>0&&document.body?(document.body.innerText||'').slice(0,pageText):'';")
      .plus("return JSON.stringify({nodes:out,counts:{matched:matched,returned:out.length,omitted:omitted,chars:chars,truncated:omitted>0},pageText:text,skippedSelectors:skipped});")
      .plus("})()")
    val started = onUi {
      val view = views[tab] ?: return@onUi false
      val url = view.url
      view.evaluateJavascript(script) { value ->
        try {
          if (views[tab] === view && view.url == url && value != null) {
            payload = JSONTokener(value).nextValue() as? String
          }
        } catch (error: org.json.JSONException) {
          Log.w(TAG, "invalid page extraction result", error)
        } finally {
          answered.countDown()
        }
      }
      true
    } ?: false
    if (!started || !answered.await(6, TimeUnit.SECONDS)) {
      Log.w(TAG, "page did not answer the html request in time")
      return timeout
    }
    return payload ?: timeout
  }

}
