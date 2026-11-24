package com.lamtools.sunday.core

import android.content.Context

/**
 * Rust's only handle on the background connection service.
 *
 * user:“简单可靠易用”+(界面只表达「保活开/关」，不碰 Android 服务生命周期；Rust 通过
 * 这个极薄的桥转成一次 start/stop，真正的连接仍然只有一套)。
 */
object ConnectionServiceBridge {
  private var context: Context? = null

  init {
    System.loadLibrary("sunday_android_host_lib")
    nativeRegister()
  }

  /** Hands Rust the JavaVM and this class, so commands can call the methods below. */
  @JvmStatic external fun nativeRegister()

  /** Called from `MainActivity.onCreate`; also resumes a previously enabled service. */
  @JvmStatic
  fun attach(applicationContext: Context) {
    context = applicationContext
    if (SundayConnectionService.wanted(applicationContext)) {
      SundayConnectionService.start(applicationContext)
    }
  }

  @JvmStatic
  fun start() {
    context?.let { SundayConnectionService.start(it) }
  }

  @JvmStatic
  fun stop() {
    context?.let { SundayConnectionService.stop(it) }
  }

  @JvmStatic
  fun running(): Boolean = SundayConnectionService.running

  @JvmStatic
  fun wanted(): Boolean = context?.let { SundayConnectionService.wanted(it) } ?: false
}
