package com.lamtools.mobile

import android.content.Context
import android.os.Bundle
import androidx.activity.enableEdgeToEdge

private object RustTlsVerifier {
  init {
    System.loadLibrary("sunday_mobile_lib")
  }

  external fun initialize(context: Context)
}

class MainActivity : TauriActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    // Rust must be loaded before Tauri's onCreate starts the native runtime.
    RustTlsVerifier.initialize(applicationContext)
    enableEdgeToEdge()
    super.onCreate(savedInstanceState)
  }
}
