package com.lamtools.sunday.core

import android.content.Intent
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import java.lang.ref.WeakReference

/**
 * 把实时扫码接进 Rust 的请求通道。
 *
 * 结果沿用文件选择器那条回传路径（`FilePickerBridge.nativeDeliver`），所以 Rust 侧
 * 只需要一条“等一个字符串”的通道，不需要为扫码再发明一套协议。
 */
object QrScanBridge {
  init {
    System.loadLibrary("sunday_android_host_lib")
    nativeRegister()
  }

  @JvmStatic
  external fun nativeRegister()

  /** 一帧亮度面里有没有二维码；没有就返回 null。 */
  @JvmStatic
  external fun nativeDecode(width: Int, height: Int, data: ByteArray): String?

  private var host: WeakReference<MainActivity>? = null
  private var launcher: ActivityResultLauncher<Intent>? = null

  /** 在 MainActivity.onCreate 里注册，结果通道只能在启动前挂好。 */
  @JvmStatic
  fun attach(activity: MainActivity) {
    host = WeakReference(activity)
    launcher = activity.registerForActivityResult(
      ActivityResultContracts.StartActivityForResult(),
    ) { result ->
      val text = result.data?.getStringExtra(QrScanActivity.EXTRA_TEXT) ?: ""
      val request = QrScanActivity.pendingRequest
      QrScanActivity.pendingRequest = ""
      if (request.isNotEmpty()) FilePickerBridge.nativeDeliver(request, text)
    }
  }

  /** Rust 通过 FilePickerBridge.scanQr 转到里。取消或失败都会回一个空字符串。 */
  @JvmStatic
  fun scan(requestId: String) {
    val activity = host?.get()
    if (activity == null) {
      FilePickerBridge.nativeDeliver(requestId, "")
      return
    }
    QrScanActivity.pendingRequest = requestId
    activity.runOnUiThread {
      val runner = launcher
      if (runner == null) {
        FilePickerBridge.nativeDeliver(requestId, "")
      } else {
        runner.launch(Intent(activity, QrScanActivity::class.java))
      }
    }
  }
}
