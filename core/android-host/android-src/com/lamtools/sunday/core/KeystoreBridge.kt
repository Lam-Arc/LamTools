package com.lamtools.sunday.core

import android.security.keystore.KeyGenParameterSpec
import android.util.Log
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * The provider API key, sealed by a key the app cannot read out.
 *
 * That is the whole point: an AES key generated inside AndroidKeyStore never leaves it,
 * so the stored blob is useless on another device, after a backup restore, or to
 * anything that gets `run-as` on a debuggable build. A file with owner-only permissions
 * protects against other apps; it does not protect against an image of the device.
 *
 * The Rust side asks for this through JNI. When any of it fails, the failure is
 * returned as an error and the caller stores nothing: falling back to a plaintext file
 * would silently undo the property this class exists to provide.
 */
object KeystoreBridge {
  private const val PROVIDER = "AndroidKeyStore"
  private const val ALIAS = "sunday.provider.key.v1"
  private const val TRANSFORMATION = "AES/GCM/NoPadding"
  private const val IV_BYTES = 12
  private const val TAG_BITS = 128
  private const val TAG = "SundayKeystore"

  init {
    System.loadLibrary("sunday_android_host_lib")
    // Hands the JavaVM to Rust so it can call back into this object.
    nativeRegister()
  }

  @JvmStatic external fun nativeRegister()

  /**
   * Forces this object's initialiser to run, which is when the JavaVM is handed to
   * Rust. Called from `MainActivity.onCreate` before Tauri starts; it does nothing else.
   */
  @JvmStatic
  fun register() = Unit

  /** True only when a working key can be produced right now. */
  @JvmStatic
  fun available(): Boolean = unavailableReason().isEmpty()

  /**
   * Why the keystore is not usable, or an empty string when it is.
   *
   * The stack also goes to logcat: a message alone rarely explains a keystore
   * refusal, and the caller only needs a short line to show.
   */
  @JvmStatic
  fun unavailableReason(): String = try {
    Log.d(TAG, "unavailableReason entered")
    key()
    ""
  } catch (error: Throwable) {
    Log.e(TAG, "the Android keystore refused to produce a key", error)
    "${error.javaClass.simpleName}: ${error.message}"
  }

  @JvmStatic
  fun seal(plain: String): String {
    val cipher = Cipher.getInstance(TRANSFORMATION)
    cipher.init(Cipher.ENCRYPT_MODE, key())
    val iv = cipher.iv
    val body = cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
    val combined = ByteArray(iv.size + body.size)
    System.arraycopy(iv, 0, combined, 0, iv.size)
    System.arraycopy(body, 0, combined, iv.size, body.size)
    return Base64.encodeToString(combined, Base64.NO_WRAP)
  }

  @JvmStatic
  fun open(sealed: String): String {
    val combined = Base64.decode(sealed, Base64.NO_WRAP)
    if (combined.size <= IV_BYTES) throw IllegalArgumentException("sealed value is truncated")
    val iv = combined.copyOfRange(0, IV_BYTES)
    val body = combined.copyOfRange(IV_BYTES, combined.size)
    val cipher = Cipher.getInstance(TRANSFORMATION)
    cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(TAG_BITS, iv))
    return String(cipher.doFinal(body), Charsets.UTF_8)
  }

  private fun key(): SecretKey {
    val store = KeyStore.getInstance(PROVIDER).apply { load(null) }
    val existing = store.getEntry(ALIAS, null)
    if (existing is KeyStore.SecretKeyEntry) {
      return existing.secretKey
    }
    val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, PROVIDER)
    generator.init(
      KeyGenParameterSpec.Builder(
        ALIAS,
        KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
      )
        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
        .setKeySize(256)
        // No user-authentication requirement: the key is used while the app runs, often
        // without the screen being unlocked by the user at that moment.
        .build()
    )
    return generator.generateKey()
  }
}
