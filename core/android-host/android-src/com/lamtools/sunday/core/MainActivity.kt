package com.lamtools.sunday.core

import android.os.Bundle
import androidx.activity.enableEdgeToEdge

class MainActivity : TauriActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    enableEdgeToEdge()
    // Touch the keystore bridge before Tauri starts. Its initialiser is what hands the
    // JavaVM to Rust, and Kotlin only initialises an object when something refers to
    // it: Rust runs its setup inside `super.onCreate`, earlier than any callback.
    KeystoreBridge.register()
    super.onCreate(savedInstanceState)
    // The file picker registers its result contract here, which has to happen before the
    // activity is started. Touching the object also runs its initialiser, which is what
    // hands the JavaVM to Rust.
    FilePickerBridge.attach(this)
  }

  /**
   * Focus was lost. This also fires for a rotation, for a split-screen divider drag
   * and for a permission dialog, so nothing here may be expensive: the Rust side
   * records a timestamp in memory and stops.
   */
  override fun onPause() {
    super.onPause()
    LifecycleBridge.signal("pause")
  }

  /**
   * No longer visible. This is the event that means background, and it is the only
   * one that is reported as such.
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

  /**
   * The activity is going away. Reported before the superclass teardown so the state
   * this writes cannot race the teardown. A rotation reaches here as well, which is
   * why the Rust side records the process as well as the goodbye.
   */
  override fun onDestroy() {
    LifecycleBridge.signal("destroy")
    super.onDestroy()
  }
}
