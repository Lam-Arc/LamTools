import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const native = vi.hoisted(() => ({ invoke: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: native.invoke }))
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn(async () => vi.fn()) }))
vi.mock('@tauri-apps/api/app', () => ({ getVersion: vi.fn(async () => '0.1.31') }))

import { checkStandaloneUpdate, MOBILE_UPDATE_MANIFEST } from '../src/standalone/StandaloneUpdate'

const manifest = {
  version: '0.1.32',
  download_url: 'https://47.114.43.99.nip.io/downloads/Sunday-mobile-latest.apk',
  release_url: 'https://47.114.43.99.nip.io/#download',
  release_notes: 'Sunday Mobile 0.1.32',
}

describe('the in-app update check', () => {
  beforeEach(() => {
    native.invoke.mockReset()
    vi.unstubAllGlobals()
  })

  afterEach(() => vi.unstubAllGlobals())

  it('asks the host, so the release site cannot break the check with a missing CORS header', async () => {
    // The 2026-09-25 report: the site answered 200 without
    // `Access-Control-Allow-Origin`, the WebView discarded it, and the app could
    // only say `Failed to fetch`. The host path does not go through the browser.
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    const browserFetch = vi.fn()
    vi.stubGlobal('fetch', browserFetch)
    native.invoke.mockResolvedValue(manifest)

    const result = await checkStandaloneUpdate('0.1.31')

    expect(native.invoke).toHaveBeenCalledWith('sunday_update_manifest', { url: MOBILE_UPDATE_MANIFEST })
    expect(browserFetch).not.toHaveBeenCalled()
    expect(result).toMatchObject({
      status: 'update_available',
      current_version: '0.1.31',
      latest_version: '0.1.32',
      download_url: manifest.download_url,
    })
  })

  it('reports the status the host saw, with the address that failed', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    native.invoke.mockRejectedValue('update manifest HTTP 404')

    const result = await checkStandaloneUpdate('0.1.31')

    expect(result.status).toBe('check_failed')
    expect(String(result.error)).toContain('HTTP 404')
    expect(String(result.error)).toContain(MOBILE_UPDATE_MANIFEST)
  })

  it('falls back to fetch outside the shell, where there is no host to ask', async () => {
    vi.stubGlobal('window', {})
    const browserFetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => manifest }))
    vi.stubGlobal('fetch', browserFetch)

    const result = await checkStandaloneUpdate('0.1.30')

    expect(browserFetch).toHaveBeenCalledWith(
      MOBILE_UPDATE_MANIFEST,
      expect.objectContaining({ cache: 'no-store' }),
    )
    expect(result).toMatchObject({ status: 'update_available', latest_version: '0.1.32' })
  })

  it('names the reason a browser fetch was discarded', async () => {
    vi.stubGlobal('window', {})
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))

    const result = await checkStandaloneUpdate('0.1.30')

    expect(result.status).toBe('check_failed')
    expect(String(result.error)).toContain('Failed to fetch')
    expect(String(result.error)).toContain(MOBILE_UPDATE_MANIFEST)
  })

  it('offers the in-app install only with a digest, on Android, in the shell', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8)' })
    native.invoke.mockResolvedValue({ ...manifest, sha256: 'c'.repeat(64), size: 60_813_364 })

    const withDigest = await checkStandaloneUpdate('0.1.32')

    expect(withDigest.sha256).toBe('c'.repeat(64))
    expect(withDigest.install_supported).toBe(true)
    expect(String(withDigest.install_hint)).toContain('立即安装')

    // A digest nobody can check against is not a digest.
    native.invoke.mockResolvedValue({ ...manifest, sha256: 'not-a-digest' })
    const brokenDigest = await checkStandaloneUpdate('0.1.32')
    expect(brokenDigest.install_supported).toBe(false)
    expect(brokenDigest.sha256).toBeUndefined()

    // Off the phone there is no package installer to hand the file to.
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' })
    native.invoke.mockResolvedValue({ ...manifest, sha256: 'c'.repeat(64) })
    const desktopShell = await checkStandaloneUpdate('0.1.32')
    expect(desktopShell.install_supported).toBe(false)
  })

  it('refuses a manifest whose version is not a version', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    native.invoke.mockResolvedValue({ ...manifest, version: 'latest' })

    const result = await checkStandaloneUpdate('0.1.31')

    expect(result.status).toBe('check_failed')
    expect(String(result.error)).toContain('版本号无效')
  })

  it('ranks versions the way the desktop does', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    const cases: Array<[string, string, string]> = [
      ['0.1.31', '0.1.32', 'update_available'],
      ['0.1.31', '0.1.31', 'up_to_date'],
      ['0.1.31', '0.1.30', 'up_to_date'],
      ['0.1.30.0', '0.1.30', 'up_to_date'],
      ['0.3.7-beta.1', '0.3.7', 'update_available'],
      ['0.3.7', '0.3.7-beta.2', 'up_to_date'],
      ['0.3.7-beta.1', '0.3.7-beta.2', 'update_available'],
    ]
    for (const [installed, latest, expected] of cases) {
      native.invoke.mockResolvedValue({ ...manifest, version: latest })
      const result = await checkStandaloneUpdate(installed)
      expect([installed, latest, result.status]).toEqual([installed, latest, expected])
    }
  })
})
