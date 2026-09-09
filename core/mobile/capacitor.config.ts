import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'com.lamtools.mobile',
  appName: 'LamTool',
  webDir: 'dist',
  server: {
    // Set CAPACITOR_SERVER_URL only for local device development. Release
    // builds use the bundled dist output and never expose Core directly.
    ...(process.env.CAPACITOR_SERVER_URL ? { url: process.env.CAPACITOR_SERVER_URL } : {}),
  },
}

export default config
