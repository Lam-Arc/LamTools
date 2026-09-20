import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import config from '../capacitor.config'

const manifest = readFileSync(
  new URL('../android/app/src/main/AndroidManifest.xml', import.meta.url),
  'utf8',
)

describe('Android LAN gateway policy', () => {
  it('keeps the bundled WebView origin compatible with HTTP and WebSocket gateways', () => {
    expect(config.server?.androidScheme).toBe('http')
    expect(manifest).toContain('android:usesCleartextTraffic="true"')
  })
})
