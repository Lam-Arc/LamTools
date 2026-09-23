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
  it('allows the native verifier to fetch only the GTS signed HTTP CRL in release', () => {
    expect(tauriAndroidManifest).toContain('android:networkSecurityConfig="@xml/network_security_config"')
    expect(releaseNetworkSecurityConfig).toMatch(/<base-config\s+cleartextTrafficPermitted="false"\s*\/>/)
    expect([...releaseNetworkSecurityConfig.matchAll(/<domain(?:\s+[^>]*)?>([^<]+)<\/domain>/g)]
      .map((match) => match[1])).toEqual(['c.pki.goog'])
    expect(releaseNetworkSecurityConfig).toContain('<domain includeSubdomains="false">c.pki.goog</domain>')
    expect(releaseNetworkSecurityConfig).toMatch(/<domain-config\s+cleartextTrafficPermitted="true"\s*>/)
    expect(debugNetworkSecurityConfig).toMatch(/<base-config\s+cleartextTrafficPermitted="true"\s*\/>/)
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

  it('renders a visible startup failure instead of leaving an empty black webview', () => {
    expect(entrySource).toContain("void import('./App.vue')")
    expect(entrySource).toContain("title.textContent = 'Sunday 启动失败'")
    expect(entrySource).toContain("window.addEventListener('unhandledrejection'")
    expect(entrySource).toContain('root.replaceChildren(surface)')
  })
})
