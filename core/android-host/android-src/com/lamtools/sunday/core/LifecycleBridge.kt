package com.lamtools.sunday.core

/**
 * The Android lifecycle, reported straight into Rust.
 *
 * This exists because the webview cannot be the source of these signals. Android
 * throttles and freezes a backgrounded webview first, so a lifecycle event that
 * starts in JavaScript arrives exactly when it is least useful, or not at all.
 *
 * Tauri does expose `onPause` and `onResume` to Rust as window events, but it has no
 * equivalent for `onStop`, and `onStop` is the only callback that means "no longer
 * visible". `onPause` fires on a rotation and on a permission dialog too, so treating
 * it as "backgrounded" would be wrong most of the times it fires.
 */
object LifecycleBridge {
  init {
    // Self-contained on purpose: an Activity callback must never be the first thing
    // that discovers the native library was not loaded.
    System.loadLibrary("sunday_android_host_lib")
  }

  /**
   * One of `pause`, `stop`, `resume`, `destroy`.
   *
   * Every one of them is cheap on this side: `pause` writes nothing, `stop` writes
   * one small file, and `resume` is the only one that reads the journal.
   */
  @JvmStatic external fun signal(event: String)
}
