import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * The transport's half of the in-app update: `update.check` records the release
 * it verified, and only that release can be downloaded and installed.
 *
 * Host-authoritative by design — `update.download` and `update.install` take no
 * arguments, so the UI cannot aim the installer at a URL or path of its own.
 */
const native = vi.hoisted(() => ({ invoke: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: native.invoke }))
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn(async () => vi.fn()) }))
vi.mock('@tauri-apps/api/app', () => ({ getVersion: vi.fn(async () => '0.1.32') }))

import { StandaloneTransport } from '../src/standalone/StandaloneTransport'
import type { LocalDatabase } from '../src/storage/Database'
import { createLocalRepository, type LocalState } from '../src/storage'

const MANIFEST_URL = 'https://47.114.43.99.nip.io/downloads/mobile-update.json'
const APK_URL = 'https://47.114.43.99.nip.io/downloads/Sunday-mobile-latest.apk'
const DIGEST = 'd'.repeat(64)

class MemoryDatabase implements LocalDatabase<LocalState> {
  value: LocalState | null = null
  async open() {}
  async read() { return this.value }
  async write(value: LocalState) { this.value = JSON.parse(JSON.stringify(value)) as LocalState }
  async close() {}
}

function transport() {
  const repository = createLocalRepository(new MemoryDatabase())
  return new StandaloneTransport(
    repository,
    {
      handleRpc: async () => null,
      activeModel: async () => {
        throw new Error('not used')
      },
      runtimeModels: async () => [],
      settings: async () => ({}),
      subAgentRuntime: async () => ({ enabled: false, guide: '' }),
    } as never,
  )
}

function routeInvoke(options: { digest?: string; installSupported?: boolean } = {}) {
  const { digest = DIGEST, installSupported = true } = options
  native.invoke.mockImplementation(async (command: string) => {
    // The transport boots the standalone stores, which read their own state.
    if (command === 'local_state_read') return null
    if (command === 'local_state_write') return null
    if (command === 'sunday_update_manifest') {
      return {
        version: '0.1.33',
        download_url: APK_URL,
        release_url: 'https://47.114.43.99.nip.io/#download',
        ...(installSupported ? { sha256: digest, size: 60_813_364 } : {}),
      }
    }
    if (command === 'sunday_update_download') {
      return { ok: true, state: 'downloading', fileName: 'Sunday-mobile-latest.apk' }
    }
    if (command === 'sunday_update_status') {
      // The host finishes the transfer and verifies it, then says so.
      return {
        ok: true, state: 'verified', received: 60_813_364, total: 60_813_364,
        fileName: 'Sunday-mobile-latest.apk', sha256: digest,
        message: '已下载并校验 Sunday-mobile-latest.apk',
      }
    }
    if (command === 'sunday_update_install') return { ok: true, launched: true, message: '已交给系统安装器' }
    throw new Error(`unexpected command ${command}`)
  })
}

describe('the transport update path', () => {
  beforeEach(() => {
    native.invoke.mockReset()
    vi.unstubAllGlobals()
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8)' })
  })

  afterEach(() => vi.unstubAllGlobals())

  it('starts the download, watches it, then installs the verified file', async () => {
    routeInvoke()
    const transport_ = transport()

    const checked = await transport_.request<Record<string, unknown>>({ method: 'update.check', params: {} })
    expect(checked.status).toBe('update_available')
    expect(checked.install_supported).toBe(true)

    // Starting returns at once: the transfer runs in the host.
    const started = await transport_.request<Record<string, unknown>>({ method: 'update.download', params: {} })
    expect(native.invoke).toHaveBeenCalledWith('sunday_update_download', {
      url: APK_URL,
      sha256: DIGEST,
      fileName: 'Sunday-mobile-latest.apk',
    })
    expect(started.state).toBe('downloading')

    const status = await transport_.request<Record<string, unknown>>({ method: 'update.status', params: {} })
    expect(native.invoke).toHaveBeenCalledWith('sunday_update_status')
    expect(status.state).toBe('verified')
    expect(status.received).toBe(60_813_364)

    // Installing takes no arguments: the host owns the verified file.
    const installed = await transport_.request<Record<string, unknown>>({ method: 'update.install', params: {} })
    expect(native.invoke).toHaveBeenCalledWith('sunday_update_install')
    expect(installed.ok).toBe(true)
  })

  it('refuses to download or install before a verified check', async () => {
    routeInvoke()
    // The host is the authority on both: it refuses an install it did not verify.
    native.invoke.mockImplementation(async (command: string) => {
      if (command === 'local_state_read' || command === 'local_state_write') return null
      if (command === 'sunday_update_install') throw '尚未下载并校验安装包'
      throw new Error(`unexpected command ${command}`)
    })
    const transport_ = transport()

    await expect(transport_.request({ method: 'update.download', params: {} }))
      .rejects.toThrow('没有已确认的更新')
    await expect(transport_.request({ method: 'update.install', params: {} }))
      .rejects.toThrow('尚未下载并校验安装包')
    expect(native.invoke).not.toHaveBeenCalledWith('sunday_update_download', expect.anything())
  })

  it('does not offer a download when the manifest carries no digest', async () => {
    routeInvoke({ installSupported: false })
    const transport_ = transport()

    const checked = await transport_.request<Record<string, unknown>>({ method: 'update.check', params: {} })
    expect(checked.install_supported).toBe(false)

    await expect(transport_.request({ method: 'update.download', params: {} }))
      .rejects.toThrow('没有已确认的更新')
  })

  it('surfaces the host refusing an install without a verified download', async () => {
    routeInvoke()
    native.invoke.mockImplementation(async (command: string) => {
      if (command === 'local_state_read' || command === 'local_state_write') return null
      if (command === 'sunday_update_manifest') {
        return { version: '0.1.33', download_url: APK_URL, sha256: DIGEST }
      }
      if (command === 'sunday_update_download') return { ok: true, state: 'downloading' }
      if (command === 'sunday_update_status') {
        return { ok: true, state: 'failed', received: 0, total: 0, error: 'downloaded update does not match the manifest sha256' }
      }
      if (command === 'sunday_update_install') throw '尚未下载并校验安装包'
      throw new Error(`unexpected command ${command}`)
    })
    const transport_ = transport()
    await transport_.request({ method: 'update.check', params: {} })

    const status = await transport_.request<Record<string, unknown>>({ method: 'update.status', params: {} })
    expect(status.state).toBe('failed')
    expect(String(status.error)).toContain('does not match')

    await expect(transport_.request({ method: 'update.install', params: {} }))
      .rejects.toThrow('尚未下载并校验安装包')
  })
})
