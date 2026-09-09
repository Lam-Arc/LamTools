import Foundation
import Darwin
import Capacitor

@objc(LamToolsLanDiscoveryPlugin)
public class LamToolsLanDiscoveryPlugin: CAPPlugin, CAPBridgedPlugin, NetServiceBrowserDelegate, NetServiceDelegate {
    public let identifier = "LamToolsLanDiscoveryPlugin"
    public let jsName = "LamToolsLanDiscovery"
    public let pluginMethods: [CAPPluginMethod] = [CAPPluginMethod(name: "discover", returnType: CAPPluginReturnPromise)]
    private var browser: NetServiceBrowser?
    private var services: [NetService] = []
    private var devices: [[String: Any]] = []
    private var pendingCall: CAPPluginCall?

    @objc func discover(_ call: CAPPluginCall) {
        pendingCall = call
        devices = []
        services = []
        let browser = NetServiceBrowser()
        browser.delegate = self
        self.browser = browser
        browser.searchForServices(ofType: "_lamtools._tcp.", inDomain: "local.")
        let timeout = min(max(call.getInt("timeoutMs") ?? 1200, 250), 5000)
        DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(timeout)) { [weak self] in self?.finish() }
    }

    public func netServiceBrowser(_ browser: NetServiceBrowser, didFind service: NetService, moreComing: Bool) {
        services.append(service)
        service.delegate = self
        service.resolve(withTimeout: 2)
    }

    public func netServiceDidResolveAddress(_ sender: NetService) {
        guard let data = sender.txtRecordData(),
              let idData = NetService.dictionary(fromTXTRecord: data)["device_id"],
              let deviceId = String(data: idData, encoding: .utf8),
              let address = sender.addresses?.compactMap({ host(from: $0) }).first else { return }
        let records = NetService.dictionary(fromTXTRecord: data)
        devices.append([
            "deviceId": deviceId,
            "protocolVersion": records["protocol_version"].flatMap { String(data: $0, encoding: .utf8) } ?? "1",
            "name": sender.name,
            "host": address,
            "port": sender.port,
        ])
    }

    private func finish() {
        guard let call = pendingCall else { return }
        pendingCall = nil
        browser?.stop()
        browser = nil
        call.resolve(["devices": devices])
    }

    private func host(from data: Data) -> String? {
        return data.withUnsafeBytes { raw in
            guard let base = raw.baseAddress?.assumingMemoryBound(to: sockaddr.self) else { return nil }
            var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            let length = socklen_t(data.count)
            guard getnameinfo(base, length, &host, socklen_t(host.count), nil, 0, NI_NUMERICHOST) == 0 else { return nil }
            return String(cString: host).split(separator: "%").first.map(String.init)
        }
    }
}
