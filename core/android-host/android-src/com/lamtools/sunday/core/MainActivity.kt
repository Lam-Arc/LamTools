package com.lamtools.sunday.core

import android.os.Bundle
import androidx.activity.enableEdgeToEdge

class MainActivity : TauriActivity() {
  companion object {
    private var alive: java.lang.ref.WeakReference<MainActivity>? = null

    /** The activity, for a bridge that needs a context: opening a file, mostly. */
    fun current(): MainActivity? = alive?.get()

    init {
      // Rust needs one fact from Android that it cannot read on its own: where the
      // packaged `.so` files were extracted. Since Android 10 a binary in app data
      // cannot be executed, but the same bytes under nativeLibraryDir can, and proot
      // is exactly such a binary.
      System.loadLibrary("sunday_android_host_lib")
    }
  }

  /** Hands `applicationInfo.nativeLibraryDir` to the host before anything starts. */
  private external fun nativeSetLibraryDir(path: String)

  /** Hands `filesDir` over: the host keeps its runtime and its database there. */
  private external fun nativeSetFilesDir(path: String)

  override fun onCreate(savedInstanceState: Bundle?) {
    alive = java.lang.ref.WeakReference(this)
    enableEdgeToEdge()
    nativeSetLibraryDir(applicationInfo.nativeLibraryDir)
    nativeSetFilesDir(filesDir.absolutePath)
    // Touch the keystore bridge before Tauri starts. Its initialiser is what hands the
    // JavaVM to Rust, and Kotlin only initialises an object when something refers to
    // it: Rust runs its setup inside `super.onCreate`, earlier than any callback.
    KeystoreBridge.register()
    // Staging the packaged runtime takes seconds the first time and does no work after
    // that; it must not delay the first frame, and the host waits for its marker before
    // it tries to install.
    Thread({ RuntimeAssets.ensure(applicationContext) }, "sunday-runtime-assets").start()
    super.onCreate(savedInstanceState)
    // The file picker registers its result contract here, which has to happen before the
    // activity is started. Touching the object also runs its initialiser, which is what
    // hands the JavaVM to Rust.
    FilePickerBridge.attach(this)
    // The window does not shrink for the keyboard (edge to edge), so the interface can
    // only learn how much it covers from here.
    KeyboardBridge.watch(this)
  }

  /**
   * Focus was lost. This also fires for a rotation, for a split-screen divider drag
   * and for a permission dialog, so nothing here may be expensive: the host records a
   * timestamp and the guest re-reads its own state when the UI comes back.
   */
  override fun onPause() {
    super.onPause()
    LifecycleBridge.signal("pause")
  }

  /**
   * No longer visible. This is the event that means background, and it is the only
   * one that is reported as such. A running turn is not cancelled here: Android kills
   * the process when it actually needs the memory, and the core journals turns so a
   * restarted app can report what was interrupted.
   */
  override fun onStop() {
    super.onStop()
    LifecycleBridge.signal("stop")
  }

  /** Visible again, in this process or in a new one. */
  override fun onResume() {
    super.onResume()
    LifecycleBridge.signal("resume")
  }
}
