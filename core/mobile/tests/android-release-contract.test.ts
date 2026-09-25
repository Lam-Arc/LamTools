import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const tauriAndroidStrings = readFileSync(
  new URL('../src-tauri/gen/android/app/src/main/res/values/strings.xml', import.meta.url),
  'utf8',
)
const tauriAndroidManifest = readFileSync(
  new URL('../src-tauri/gen/android/app/src/main/AndroidManifest.xml', import.meta.url),
  'utf8',
)
const releaseNetworkSecurityConfig = readFileSync(
  new URL('../src-tauri/gen/android/app/src/main/res/xml/network_security_config.xml', import.meta.url),
  'utf8',
)
const debugNetworkSecurityConfig = readFileSync(
  new URL('../src-tauri/gen/android/app/src/debug/res/xml/network_security_config.xml', import.meta.url),
  'utf8',
)
const tauriConfig = JSON.parse(readFileSync(
  new URL('../src-tauri/tauri.conf.json', import.meta.url),
  'utf8',
)) as { app?: { security?: { csp?: string } } }
const entrySource = readFileSync(new URL('../src/main.ts', import.meta.url), 'utf8')

describe('Android release identity contract', () => {
  it('permits LAN cleartext in release and keeps the GTS CRL exception', () => {
    // 局域网直连（ws://）与配对（http://）是既定功能，正式包必须放行明文；
    // 账户/中继通道仍是 https/wss（2026-09-25 审计：原先 release 双重禁止，
    // 只有 debug 包能用局域网直连）。
    expect(tauriAndroidManifest).toContain('android:networkSecurityConfig="@xml/network_security_config"')
    expect(releaseNetworkSecurityConfig).toMatch(/<base-config\s+cleartextTrafficPermitted="true"\s*\/>/)
    expect([...releaseNetworkSecurityConfig.matchAll(/<domain(?:\s+[^>]*)?>([^<]+)<\/domain>/g)]
      .map((match) => match[1])).toEqual(['c.pki.goog'])
    expect(releaseNetworkSecurityConfig).toContain('<domain includeSubdomains="false">c.pki.goog</domain>')
    expect(releaseNetworkSecurityConfig).toMatch(/<domain-config\s+cleartextTrafficPermitted="true"\s*>/)
    expect(debugNetworkSecurityConfig).toMatch(/<base-config\s+cleartextTrafficPermitted="true"\s*\/>/)
    // AndroidManifest 的占位默认值必须与网络安全策略一致
    const gradle = readFileSync(
      new URL('../src-tauri/gen/android/app/build.gradle.kts', import.meta.url),
      'utf8',
    )
    expect(gradle).toContain('manifestPlaceholders["usesCleartextTraffic"] = "true"')
  })

  it('uses Sunday for the launcher and activity labels', () => {
    const androidString = (name: string): string | null => {
      const match = tauriAndroidStrings.match(new RegExp(`<string\\s+name="${name}">([^<]*)</string>`))
      if (!match) return null
      const value = match[1].trim()
      // Tauri emits Android's quoted string syntax; those delimiters are not
      // part of the resource value consumed by Android.
      return value.startsWith('"') && value.endsWith('"') ? value.slice(1, -1) : value
    }

    expect(tauriAndroidManifest).toMatch(/<application[\s\S]*?android:label="@string\/app_name"/)
    expect(tauriAndroidManifest).toMatch(/<activity[\s\S]*?android:label="@string\/main_activity_title"/)
    expect(androidString('app_name')).toBe('Sunday')
    expect(androidString('main_activity_title')).toBe('Sunday')
  })

  it('allows only the WebAssembly compilation required by the encrypted tunnel', () => {
    const csp = tauriConfig.app?.security?.csp || ''
    expect(csp).toContain("script-src 'self' 'wasm-unsafe-eval'")
    expect(csp).not.toMatch(/script-src[^;]*'unsafe-eval'/)
  })

  it('lets the webview reach LAN hosts over plain http/ws', () => {
    const csp = tauriConfig.app?.security?.csp || ''
    const connectSrc = csp.split(';').map((part) => part.trim()).find((part) => part.startsWith('connect-src')) || ''
    // 局域网直连与配对的目标是 http://<ip>:<port> / ws://<ip>:<port>（CSP 无法
    // 表达 IP 段，所以放行整类协议；桌面的 connect-src 出于同一原因也列了
    // http://127.0.0.1:* 与 ws://127.0.0.1:*）。
    expect(connectSrc).toContain('http:')
    expect(connectSrc).toContain('ws:')
    expect(connectSrc).toContain('https:')
    expect(connectSrc).toContain('wss:')
  })

  it('renders a visible startup failure instead of leaving an empty black webview', () => {
    expect(entrySource).toContain("void import('./App.vue')")
    expect(entrySource).toContain("title.textContent = 'Sunday 启动失败'")
    expect(entrySource).toContain("window.addEventListener('unhandledrejection'")
    expect(entrySource).toContain('root.replaceChildren(surface)')
  })
})
