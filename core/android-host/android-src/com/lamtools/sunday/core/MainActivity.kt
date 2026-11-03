package com.lamtools.sunday.core

import android.os.Bundle
import androidx.activity.enableEdgeToEdge

class MainActivity : TauriActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    enableEdgeToEdge()
    super.onCreate(savedInstanceState)
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
