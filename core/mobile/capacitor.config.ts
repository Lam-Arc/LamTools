import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'com.lamtools.mobile',
  appName: 'Sunday',
  webDir: 'dist',
  server: {
    // The desktop gateway is HTTP/WebSocket on the local network, with the
    // tunnel payload protected by Noise. Keep the bundled Android origin on
    // HTTP so WebView does not reject LAN pairing as mixed content.
    androidScheme: 'http',
    // Set CAPACITOR_SERVER_URL only for local device development. Release
    // builds use the bundled dist output and never expose Core directly.
    ...(process.env.CAPACITOR_SERVER_URL ? { url: process.env.CAPACITOR_SERVER_URL } : {}),
  },
}

export default config
