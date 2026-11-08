package com.lamtools.sunday.core

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.ImageFormat
import android.hardware.Camera
import android.os.Bundle
import android.util.Log
import android.view.Gravity
import android.view.Surface
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.widget.FrameLayout
import android.widget.TextView

/**
 * 实时扫码：相机预览的每一帧亮度面直接交给 Rust 的同一个二维码解码器。
 *
 * user:“扫码还要靠拍照，而不是直接调用摄像头权限扫描识别”+(原来是拉起系统相机拍照、
 * 落盘、再由 Rust 读图；现在相机预览常开，识别到就自动返回，不再有拍照这一步)。
 *
 * 用系统自带的 `android.hardware.Camera`，不引入 CameraX/ZXing：设备上少两个依赖，
 * 解码器也只有 core/p2p 里那一个实现。
 */
class QrScanActivity : Activity(), SurfaceHolder.Callback, Camera.PreviewCallback {
  companion object {
    const val EXTRA_TEXT = "text"
    private const val TAG = "SundayQr"
    private const val REQUEST_CAMERA = 41
    /** Rust 等待的请求 id；结果通过 FilePickerBridge.nativeDeliver 回传。 */
    @Volatile
    var pendingRequest: String = ""
  }

  private var surfaceView: SurfaceView? = null
  private var root: FrameLayout? = null
  private var camera: Camera? = null
  private var previewWidth = 0
  private var previewHeight = 0
  /** 预览已经按这个角度转正；比例换算要用它，不能用传感器方向。 */
  private var previewRotation = 0
  @Volatile
  private var decoding = false
  @Volatile
  private var finished = false
  private var frameCount = 0

  override fun onCreate(state: Bundle?) {
    super.onCreate(state)
    val root = FrameLayout(this).apply { setBackgroundColor(Color.BLACK) }
    this.root = root
    val view = SurfaceView(this)
    surfaceView = view
    view.holder.addCallback(this)
    root.addView(view)
    val hint = TextView(this).apply {
      text = "把电脑上的二维码放进画面"
      setTextColor(Color.WHITE)
      textSize = 16f
      gravity = Gravity.CENTER
      setShadowLayer(4f, 0f, 1f, Color.BLACK)
    }
    root.addView(
      hint,
      FrameLayout.LayoutParams(
        FrameLayout.LayoutParams.MATCH_PARENT,
        FrameLayout.LayoutParams.WRAP_CONTENT,
        Gravity.TOP or Gravity.CENTER_HORIZONTAL,
      ).apply { topMargin = 96 },
    )
    setContentView(root)

    if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
      requestPermissions(arrayOf(Manifest.permission.CAMERA), REQUEST_CAMERA)
    }
  }

  override fun onRequestPermissionsResult(
    requestCode: Int,
    permissions: Array<out String>,
    grantResults: IntArray,
  ) {
    super.onRequestPermissionsResult(requestCode, permissions, grantResults)
    if (requestCode != REQUEST_CAMERA) return
    if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) startCamera()
    else finishCancelled()
  }

  override fun surfaceCreated(holder: SurfaceHolder) {
    startCamera()
  }

  override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {
    // 权限对话框关掉后 surface 才可能就绪；此时补一次启动。
    if (camera == null) startCamera() else fitPreview()
  }

  override fun surfaceDestroyed(holder: SurfaceHolder) {
    stopCamera()
  }

  private fun startCamera() {
    if (camera != null || finished) return
    if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) return
    val holder = surfaceView?.holder ?: return
    // 预览面还没就绪时打开相机会拿到一个 NULL surface，之后一直黑屏。
    if (!holder.surface.isValid) return
    try {
      val device = Camera.open()
      device.setPreviewDisplay(holder)
      val parameters = device.parameters
      val size = parameters.supportedPreviewSizes
        .filter { it.width <= 1280 && it.width * 9 == it.height * 16 }
        .minByOrNull { it.width }
        ?: parameters.supportedPreviewSizes.minByOrNull { it.width }
        ?: throw IllegalStateException("相机没有可用的预览尺寸")
      parameters.setPreviewSize(size.width, size.height)
      parameters.previewFormat = ImageFormat.NV21
      if (parameters.supportedFocusModes?.contains(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE) == true) {
        parameters.focusMode = Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE
      }
      // user:“这个相机有问题，显示的时候可能是什么方向没对上”+(传感器方向 90° 的手机
      // 不设显示方向时画面是横躺的；按「传感器方向 - 屏幕旋转」转正，界面拿到的就是
      // 竖着的画面，和人举着手机看到的一致)。
      val info = Camera.CameraInfo()
      Camera.getCameraInfo(0, info)
      val rotation = when (windowManager.defaultDisplay.rotation) {
        Surface.ROTATION_90 -> 90
        Surface.ROTATION_180 -> 180
        Surface.ROTATION_270 -> 270
        else -> 0
      }
      var displayOrientation = (info.orientation - rotation + 360) % 360
      if (info.facing == Camera.CameraInfo.CAMERA_FACING_FRONT) {
        displayOrientation = (360 - displayOrientation) % 360
      }
      device.setDisplayOrientation(displayOrientation)
      device.parameters = parameters
      previewWidth = size.width
      previewHeight = size.height
      previewRotation = displayOrientation
      device.setPreviewCallback(this)
      fitPreview()
      device.startPreview()
      camera = device
      Log.i(
        TAG,
        "preview ${size.width}x${size.height} sensor=${info.orientation} screen=$rotation display=$displayOrientation",
      )
    } catch (error: Throwable) {
      Log.e(TAG, "cannot start the camera", error)
      finishCancelled()
    }
  }

  /**
   * 预览面按「转正之后」的比例贴合屏幕，多出来的部分留给黑底。
   *
   * user:“显示有问题”+(转正后画面是竖的，如果把 SurfaceView 拉满整屏就会被横向拉长；
   * 这里按旋转后的宽高算一个等比尺寸，居中放)。
   */
  private fun fitPreview() {
    val view = surfaceView ?: return
    val box = root ?: return
    if (previewWidth <= 0 || previewHeight <= 0) return
    val boxWidth = box.width.takeIf { it > 0 } ?: resources.displayMetrics.widthPixels
    val boxHeight = box.height.takeIf { it > 0 } ?: resources.displayMetrics.heightPixels
    val swapped = previewRotation % 180 != 0
    val fittedWidth = if (swapped) previewHeight else previewWidth
    val fittedHeight = if (swapped) previewWidth else previewHeight
    val scale = minOf(
      boxWidth.toFloat() / fittedWidth,
      boxHeight.toFloat() / fittedHeight,
    )
    val width = (fittedWidth * scale).toInt()
    val height = (fittedHeight * scale).toInt()
    if (width <= 0 || height <= 0) return
    view.layoutParams = FrameLayout.LayoutParams(width, height, Gravity.CENTER)
    view.requestLayout()
    Log.i(TAG, "surface ${width}x$height in box ${boxWidth}x$boxHeight")
  }

  override fun onPreviewFrame(data: ByteArray?, source: Camera?) {
    if (data == null || finished || decoding || previewWidth <= 0 || previewHeight <= 0) return
    // 每第三帧解一次：识别延迟仍然不到一秒，也不会把 CPU 占满。
    frameCount += 1
    if (frameCount % 3 != 0) return
    val width = previewWidth
    val height = previewHeight
    val needed = width * height
    if (data.size < needed) return
    decoding = true
    try {
      // NV21 的前 width*height 字节就是亮度面。
      val luma = data.copyOf(needed)
      val text = QrScanBridge.nativeDecode(width, height, luma)
      if (!text.isNullOrEmpty()) {
        finished = true
        runOnUiThread { finishWith(text) }
      }
    } catch (error: Throwable) {
      Log.e(TAG, "decode failed", error)
    } finally {
      decoding = false
    }
  }

  private fun finishWith(text: String) {
    setResult(RESULT_OK, Intent().putExtra(EXTRA_TEXT, text))
    finish()
  }

  private fun finishCancelled() {
    if (isFinishing) return
    setResult(RESULT_CANCELED)
    finish()
  }

  override fun onPause() {
    super.onPause()
    stopCamera()
  }

  override fun onResume() {
    super.onResume()
    if (surfaceView?.holder?.surface?.isValid == true) startCamera()
  }

  private fun stopCamera() {
    val device = camera ?: return
    camera = null
    try {
      device.setPreviewCallback(null)
      device.stopPreview()
    } catch (_: Throwable) {
    } finally {
      device.release()
    }
  }
}
