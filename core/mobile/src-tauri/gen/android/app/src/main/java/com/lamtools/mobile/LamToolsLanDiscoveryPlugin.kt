package com.lamtools.mobile

import android.app.Activity
import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Handler
import android.os.Looper
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.nio.charset.StandardCharsets
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import org.json.JSONArray

@InvokeArg
class LanDiscoveryArgs { var timeoutMs: Int = 1200 }

/** Android DNS-SD discovery for the existing LamTools desktop gateway record. */
@TauriPlugin
class LamToolsLanDiscoveryPlugin(private val activity: Activity) : Plugin(activity) {
    private val reachabilityExecutor = Executors.newFixedThreadPool(4)

    @Command
    fun discover(invoke: Invoke) {
        val args = try {
            invoke.parseArgs(LanDiscoveryArgs::class.java)
        } catch (_: Exception) {
            LanDiscoveryArgs()
        }
        val timeoutMs = args.timeoutMs.coerceIn(MIN_TIMEOUT_MS, MAX_TIMEOUT_MS)
        val manager = activity.getSystemService(Context.NSD_SERVICE) as? NsdManager
        if (manager == null) {
            invoke.resolve(JSObject().put("devices", JSONArray()))
            return
        }

        val finished = AtomicBoolean(false)
        val resolutionsStarted = AtomicInteger(0)
        val seenServices = ConcurrentHashMap.newKeySet<String>()
        val devices = linkedMapOf<String, JSObject>()
        val handler = Handler(Looper.getMainLooper())
        var listener: NsdManager.DiscoveryListener? = null

        fun finish() {
            if (!finished.compareAndSet(false, true)) return
            handler.removeCallbacksAndMessages(null)
            listener?.let { discovery ->
                try {
                    manager.stopServiceDiscovery(discovery)
                } catch (_: IllegalArgumentException) {
                    // Discovery may have failed before Android started it.
                } catch (_: RuntimeException) {
                    // A completed or failed NSD listener is already stopped.
                }
            }
            val snapshot = synchronized(devices) {
                JSONArray().apply { devices.values.forEach { put(it) } }
            }
            invoke.resolve(JSObject().put("devices", snapshot))
        }

        val discoveryListener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) = Unit
            override fun onDiscoveryStopped(serviceType: String) = Unit
            override fun onServiceLost(serviceInfo: NsdServiceInfo) = Unit
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) = finish()
            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) = finish()

            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                if (finished.get() || !serviceInfo.serviceType.contains(SERVICE_TYPE)) return
                val serviceKey = serviceInfo.serviceName
                if (!seenServices.add(serviceKey)) return
                if (resolutionsStarted.incrementAndGet() > MAX_RESOLUTIONS) return

                try {
                    manager.resolveService(serviceInfo, object : NsdManager.ResolveListener {
                        override fun onResolveFailed(info: NsdServiceInfo, errorCode: Int) = Unit

                        override fun onServiceResolved(info: NsdServiceInfo) {
                            if (finished.get()) return
                            val address = info.host ?: return
                            val deviceId = info.attributes["device_id"]
                                ?.toString(StandardCharsets.UTF_8)
                                ?.takeIf(String::isNotBlank)
                                ?: return
                            val host = address.hostAddress?.substringBefore('%') ?: return
                            val port = info.port
                            if (port !in 1..65535 || !isAddressUsable(address)) return

                            reachabilityExecutor.execute {
                                if (finished.get() || !isReachable(address, port)) return@execute
                                val candidate = JSObject()
                                    .put("deviceId", deviceId)
                                    .put("protocolVersion", info.attributes["protocol_version"]
                                        ?.toString(StandardCharsets.UTF_8) ?: "1")
                                    .put("name", info.serviceName)
                                    .put("host", host)
                                    .put("port", port)
                                val key = "$deviceId|${address.hostAddress}|$port"
                                val isFull = synchronized(devices) {
                                    if (devices.size >= MAX_CANDIDATES) {
                                        true
                                    } else {
                                        devices.putIfAbsent(key, candidate)
                                        devices.size >= MAX_CANDIDATES
                                    }
                                }
                                if (isFull) handler.post { finish() }
                            }
                        }
                    })
                } catch (_: RuntimeException) {
                    // Ignore a single service that Android could not resolve.
                }
            }
        }

        listener = discoveryListener
        handler.postDelayed({ finish() }, timeoutMs.toLong())
        try {
            manager.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, discoveryListener)
        } catch (_: RuntimeException) {
            finish()
        }
    }

    private fun isAddressUsable(address: InetAddress): Boolean =
        !address.isAnyLocalAddress &&
            !address.isLoopbackAddress &&
            !address.isMulticastAddress &&
            !address.isLinkLocalAddress

    private fun isReachable(address: InetAddress, port: Int): Boolean = try {
        Socket().use { socket ->
            socket.connect(InetSocketAddress(address, port), CONNECT_TIMEOUT_MS)
            socket.isConnected
        }
    } catch (_: Exception) {
        false
    }

    private companion object {
        const val SERVICE_TYPE = "_lamtools._tcp."
        const val MIN_TIMEOUT_MS = 250
        const val MAX_TIMEOUT_MS = 5000
        const val CONNECT_TIMEOUT_MS = 400
        const val MAX_RESOLUTIONS = 16
        const val MAX_CANDIDATES = 8
    }
}
