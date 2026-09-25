import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// 出货的是 Tauri 宿主（core/mobile/src-tauri/gen/android），不是已退役的
// Capacitor 工程：原先这里断言 ../android + capacitor.config.ts，正式包的
// 网络策略因此无人守卫（2026-09-25 审计 P3）。
const manifest = readFileSync(
  new URL('../src-tauri/gen/android/app/src/main/AndroidManifest.xml', import.meta.url),
  'utf8',
)
const gradle = readFileSync(
  new URL('../src-tauri/gen/android/app/build.gradle.kts', import.meta.url),
  'utf8',
)
const tauriConfig = JSON.parse(readFileSync(
  new URL('../src-tauri/tauri.conf.json', import.meta.url),
  'utf8',
)) as { app?: { security?: { csp?: string } } }

describe('Android LAN gateway policy', () => {
  it('keeps the shipped Tauri shell able to reach LAN gateways over http/ws', () => {
    expect(manifest).toContain('android:networkSecurityConfig="@xml/network_security_config"')
    expect(manifest).toContain('android:usesCleartextTraffic="${usesCleartextTraffic}"')
    expect(gradle).toContain('manifestPlaceholders["usesCleartextTraffic"] = "true"')

    const csp = tauriConfig.app?.security?.csp || ''
    const connectSrc = csp.split(';').map((part) => part.trim()).find((part) => part.startsWith('connect-src')) || ''
    expect(connectSrc).toMatch(/(^|\s)http:(\s|$)/)
    expect(connectSrc).toMatch(/(^|\s)ws:(\s|$)/)
  })
})
