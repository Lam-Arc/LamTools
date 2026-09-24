package com.lamtools.mobile

import android.app.Activity
import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.security.keystore.KeyPermanentlyInvalidatedException
import android.util.Base64
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.AEADBadTagException
import javax.crypto.spec.GCMParameterSpec

@InvokeArg
class SecureKeyArgs { lateinit var key: String }

@InvokeArg
class SecureSetArgs { lateinit var key: String; lateinit var value: String }

@TauriPlugin
class LamToolsSecureStoragePlugin(private val activity: Activity): Plugin(activity) {
    private val preferences by lazy {
        activity.getSharedPreferences("WSSecureStorageSharedPreferences", Context.MODE_PRIVATE)
    }

    @Command
    fun get(invoke: Invoke) {
        try {
            val args = invoke.parseArgs(SecureKeyArgs::class.java)
            val encrypted = preferences.getString(args.key, null)
            val result = JSObject()
            result.put("value", encrypted?.let { decrypt(it, args.key) })
            invoke.resolve(result)
        } catch (error: AEADBadTagException) {
            // A device transfer may restore ciphertext without its non-exportable
            // AndroidKeyStore key. Never return corrupted plaintext as an identity.
            invoke.reject("SECURE_STORAGE_KEY_INVALIDATED")
        } catch (error: KeyPermanentlyInvalidatedException) {
            invoke.reject("SECURE_STORAGE_KEY_INVALIDATED")
        } catch (error: Exception) { invoke.reject(error.message ?: "secure storage read failed") }
    }

    @Command
    fun set(invoke: Invoke) {
        try {
            val args = invoke.parseArgs(SecureSetArgs::class.java)
            preferences.edit().putString(args.key, encrypt(args.value, args.key)).apply()
            invoke.resolve(JSObject())
        } catch (error: Exception) { invoke.reject(error.message ?: "secure storage write failed") }
    }

    @Command
    fun remove(invoke: Invoke) {
        try {
            val args = invoke.parseArgs(SecureKeyArgs::class.java)
            val store = keyStore()
            if (store.containsAlias(args.key)) store.deleteEntry(args.key)
            preferences.edit().remove(args.key).apply()
            invoke.resolve(JSObject().put("success", true))
        } catch (error: Exception) { invoke.reject(error.message ?: "secure storage remove failed") }
    }

    private fun keyStore(): KeyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    private fun secretKey(alias: String): SecretKey {
        val store = keyStore()
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder(
            alias,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
        ).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        return generator.generateKey()
    }

    private fun encrypt(value: String, alias: String): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, secretKey(alias))
        val encoded = Base64.encodeToString(cipher.doFinal(value.toByteArray(Charsets.UTF_8)), Base64.NO_PADDING or Base64.NO_WRAP)
        val iv = Base64.encodeToString(cipher.iv, Base64.NO_PADDING or Base64.NO_WRAP)
        return "$encoded\u0010$iv"
    }

    private fun decrypt(value: String, alias: String): String {
        val parts = value.split('\u0010')
        require(parts.size == 2) { "invalid secure storage payload" }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        val iv = Base64.decode(parts[1], Base64.NO_PADDING or Base64.NO_WRAP)
        cipher.init(Cipher.DECRYPT_MODE, secretKey(alias), GCMParameterSpec(128, iv))
        val encrypted = Base64.decode(parts[0], Base64.NO_PADDING or Base64.NO_WRAP)
        return String(cipher.doFinal(encrypted), Charsets.UTF_8)
    }
}
