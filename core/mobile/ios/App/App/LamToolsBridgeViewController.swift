import Capacitor

final class LamToolsBridgeViewController: CAPBridgeViewController {
    override func viewDidLoad() {
        super.viewDidLoad()
        bridge?.registerPluginInstance(LamToolsLanDiscoveryPlugin())
    }
}
