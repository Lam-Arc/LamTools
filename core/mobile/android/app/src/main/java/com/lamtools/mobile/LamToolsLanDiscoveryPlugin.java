package com.lamtools.mobile;

import android.content.Context;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import android.os.Handler;
import android.os.Looper;
import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicBoolean;

@CapacitorPlugin(name = "LamToolsLanDiscovery")
public class LamToolsLanDiscoveryPlugin extends Plugin {
  @PluginMethod
  public void discover(PluginCall call) {
    int timeoutMs = Math.max(250, Math.min(call.getInt("timeoutMs", 1200), 5000));
    NsdManager manager = (NsdManager) getContext().getSystemService(Context.NSD_SERVICE);
    JSArray devices = new JSArray();
    AtomicBoolean finished = new AtomicBoolean(false);
    NsdManager.DiscoveryListener listener = new NsdManager.DiscoveryListener() {
      public void onDiscoveryStarted(String type) {}
      public void onDiscoveryStopped(String type) {}
      public void onStartDiscoveryFailed(String type, int code) { finish(); }
      public void onStopDiscoveryFailed(String type, int code) { finish(); }
      public void onServiceLost(NsdServiceInfo service) {}
      public void onServiceFound(NsdServiceInfo service) {
        if (!service.getServiceType().contains("_lamtools._tcp")) return;
        manager.resolveService(service, new NsdManager.ResolveListener() {
          public void onResolveFailed(NsdServiceInfo info, int code) {}
          public void onServiceResolved(NsdServiceInfo info) {
            JSObject device = new JSObject();
            byte[] id = info.getAttributes().get("device_id");
            byte[] version = info.getAttributes().get("protocol_version");
            if (id == null || info.getHost() == null) return;
            device.put("deviceId", new String(id, StandardCharsets.UTF_8));
            device.put("protocolVersion", version == null ? "1" : new String(version, StandardCharsets.UTF_8));
            device.put("name", info.getServiceName());
            device.put("host", info.getHost().getHostAddress());
            device.put("port", info.getPort());
            devices.put(device);
          }
        });
      }
      private void finish() {
        if (!finished.compareAndSet(false, true)) return;
        try { manager.stopServiceDiscovery(this); } catch (Exception ignored) {}
        JSObject result = new JSObject();
        result.put("devices", devices);
        call.resolve(result);
      }
    };
    manager.discoverServices("_lamtools._tcp.", NsdManager.PROTOCOL_DNS_SD, listener);
    new Handler(Looper.getMainLooper()).postDelayed(() -> {
      if (!finished.compareAndSet(false, true)) return;
      try { manager.stopServiceDiscovery(listener); } catch (Exception ignored) {}
      JSObject result = new JSObject();
      result.put("devices", devices);
      call.resolve(result);
    }, timeoutMs);
  }
}
