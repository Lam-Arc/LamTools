import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getAppVersion } from '../src/helpers/update'
import {
  readUpdateAutoCheck,
  setUpdateAutoCheck,
  useCoreUpdateState,
} from '../src/composables'

describe('useCoreUpdateState', () => {
  it('flags update_available with download url and notes', async () => {
    const rpc = vi.fn().mockResolvedValue({
      status: 'update_available',
      current_version: '0.2.2',
      latest_version: '9.9.9',
      release_notes: '## 新功能',
      download_url: 'https://example.com/Sunday_9.9.9_x64-setup.exe',
      release_url: 'https://example.com/releases/latest',
    })
    const state = useCoreUpdateState(rpc as never)

    await state.check()

    expect(rpc).toHaveBeenCalledWith('update.check', {})
    expect(state.status.value).toBe('update_available')
    expect(state.latestVersion.value).toBe('9.9.9')
    expect(state.downloadUrl.value).toContain('Sunday_9.9.9')
    expect(state.releaseNotes.value).toContain('新功能')
  })

  it('reports up_to_date', async () => {
    const state = useCoreUpdateState((async () => ({
      status: 'up_to_date',
      current_version: '0.2.2',
      latest_version: '0.2.2',
    })) as never)

    await state.check()

    expect(state.status.value).toBe('up_to_date')
  })

  it('surfaces check_failed payload errors', async () => {
    const state = useCoreUpdateState((async () => ({
      status: 'check_failed',
      current_version: '0.2.2',
      error: 'network unreachable',
    })) as never)

    await state.check()

    expect(state.status.value).toBe('check_failed')
    expect(state.error.value).toContain('network unreachable')
  })

  it('keeps the in-app install off until the manifest carries a digest', async () => {
    const withDigest = useCoreUpdateState((async () => ({
      status: 'update_available',
      current_version: '0.2.2',
      latest_version: '9.9.9',
      download_url: 'https://example.com/Sunday_9.9.9_x64-setup.exe',
      sha256: 'a'.repeat(64),
      size: 94_081_829,
      install_supported: true,
      install_hint: '点「立即安装」会运行安装包；安装向导会要求先退出 Sunday。',
    })) as never)
    const withoutDigest = useCoreUpdateState((async () => ({
      status: 'update_available',
      current_version: '0.2.2',
      latest_version: '9.9.9',
      download_url: 'https://example.com/Sunday_9.9.9_x64-setup.exe',
    })) as never)

    await withDigest.check()
    await withoutDigest.check()

    expect(withDigest.installSupported.value).toBe(true)
    expect(withDigest.installHint.value).toContain('立即安装')
    expect(withoutDigest.installSupported.value).toBe(false)
    expect(withoutDigest.installHint.value).toBe('')
  })

  it('downloads through the host and then hands the artifact to the installer', async () => {
    const rpc = vi.fn(async (method: string) => {
      if (method === 'update.check') {
        return {
          status: 'update_available',
          current_version: '0.2.2',
          latest_version: '9.9.9',
          download_url: 'https://example.com/Sunday_9.9.9_x64-setup.exe',
          sha256: 'b'.repeat(64),
          install_supported: true,
        }
      }
      if (method === 'update.download') return { ok: true, state: 'downloading' }
      if (method === 'update.status') {
        return {
          ok: true, state: 'verified', received: 94_081_829, total: 94_081_829,
          message: '已下载并校验 v9.9.9（89.7 MB）',
        }
      }
      if (method === 'update.install') return { ok: true, message: '已启动安装程序' }
      throw new Error(`unexpected ${method}`)
    })
    const state = useCoreUpdateState(rpc as never)

    await state.check()
    expect(state.installState.value).toBe('idle')
    // Installing before anything was downloaded is refused locally.
    await expect(state.runInstaller()).resolves.toBe(false)
    expect(rpc).not.toHaveBeenCalledWith('update.install', expect.anything())

    await expect(state.downloadInstaller()).resolves.toBe(true)
    expect(rpc).toHaveBeenCalledWith('update.download', {})
    expect(rpc).toHaveBeenCalledWith('update.status', {})
    expect(state.installState.value).toBe('downloaded')
    expect(state.installMessage.value).toContain('校验')

    await expect(state.runInstaller()).resolves.toBe(true)
    expect(rpc).toHaveBeenCalledWith('update.install', {})
    expect(state.installMessage.value).toContain('安装')
  })

  it('shows how far the download has come while it runs', async () => {
    let polls = 0
    const state = useCoreUpdateState((async (method: string) => {
      if (method === 'update.download') return { ok: true, state: 'downloading' }
      if (method === 'update.status') {
        polls += 1
        // Halfway through on the first look, verified on the second.
        return polls === 1
          ? { ok: true, state: 'downloading', received: 47_040_914, total: 94_081_829, message: '' }
          : { ok: true, state: 'verified', received: 94_081_829, total: 94_081_829, message: '' }
      }
      return { status: 'up_to_date', current_version: '0.2.2', latest_version: '0.2.2' }
    }) as never)
    const seen: string[] = []
    const watching = (async () => {
      for (let index = 0; index < 40 && state.installState.value !== 'downloaded'; index += 1) {
        await new Promise((resolve) => setTimeout(resolve, 50))
        if (state.installProgressLabel.value) seen.push(state.installProgressLabel.value)
      }
    })()

    await expect(state.downloadInstaller()).resolves.toBe(true)
    await watching

    expect(seen.join(' ')).toContain('正在下载 50%')
    expect(state.installState.value).toBe('downloaded')
    expect(state.installProgress.value).toBeNull()
  })

  it('surfaces a failed download without leaving the button disabled', async () => {
    const state = useCoreUpdateState((async (method: string) => (
      method === 'update.download'
        ? { ok: false, error: '下载的安装包与清单摘要不一致，已丢弃' }
        : { status: 'up_to_date', current_version: '0.2.2', latest_version: '0.2.2' }
    )) as never)

    await expect(state.downloadInstaller()).resolves.toBe(false)
    expect(state.installState.value).toBe('idle')
    expect(state.installError.value).toContain('摘要不一致')
  })

  it('folds rejected rpc into check_failed', async () => {
    const state = useCoreUpdateState((async () => {
      throw new Error('Core App Server 连接失败')
    }) as never)

    await state.check()

    expect(state.status.value).toBe('check_failed')
    expect(state.error.value).toContain('连接失败')
  })
})

describe('update auto-check preference', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => localStorage.clear())

  it('defaults to enabled', () => {
    expect(readUpdateAutoCheck()).toBe(true)
  })

  it('persists a disabled choice', () => {
    setUpdateAutoCheck(false)
    expect(readUpdateAutoCheck()).toBe(false)
    setUpdateAutoCheck(true)
    expect(readUpdateAutoCheck()).toBe(true)
  })
})

describe('getAppVersion bridge', () => {
  afterEach(() => {
    delete (window as any).__LAMTOOLS_APP_VERSION__
  })

  it('falls back to the web placeholder without the Tauri bridge', () => {
    expect(getAppVersion()).toBe('0.0.0-dev')
  })

  it('reads the version injected by the desktop shell', () => {
    ;(window as any).__LAMTOOLS_APP_VERSION__ = '0.2.2'
    expect(getAppVersion()).toBe('0.2.2')
  })
})

describe('CoreSettings 关于与更新 section (source contract)', () => {
  // The settings panel mounts inside SettingsShell and the existing test
  // environment cannot render it reliably (pre-existing recursive-update issue
  // on this branch — see core-settings.test.ts); assert the section contract
  // against the source instead.

  it('registers the about section and its data-* hooks in CoreSettings', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/components/CoreSettings.vue'), 'utf8')
    expect(source).toContain("{ id: 'about', label: '关于与更新', icon: 'info' }")
    expect(source).toContain("activeSection === 'about'")
    expect(source).toContain('data-current-version')
    expect(source).toContain('data-check-updates')
    expect(source).toContain('data-update-available')
    expect(source).toContain('data-download-update')
    expect(source).toContain('data-download-installer')
    expect(source).toContain('data-run-installer')
    expect(source).toContain('data-install-status')
    expect(source).toContain('data-open-release-page')
    expect(source).toContain('data-update-auto-check')
    expect(source).toContain('checkForUpdates()')
    expect(source).toContain('useCoreUpdateState(props.requestRpc || defaultRequestRpc)')
  })

  it('registers the info icon in SettingsShell', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/components/SettingsShell.vue'), 'utf8')
    expect(source).toContain('Info,')
    expect(source).toContain('info: Info,')
  })

  it('wires the shared update state and startup banner in the Shared Core App', () => {
const source = readFileSync(resolve(process.cwd(), 'src/app/LamToolsApp.vue'), 'utf8')
    expect(source).toContain('useCoreUpdateState(requestConfigOperation)')
    expect(source).toContain(':update-state="updateState"')
    expect(source).toContain('data-update-banner')
    expect(source).toContain('readUpdateAutoCheck()')
  })
})
