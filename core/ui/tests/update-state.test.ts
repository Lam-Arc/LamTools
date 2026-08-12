import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

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
      download_url: 'https://example.com/LamCore_9.9.9_x64-setup.exe',
      release_url: 'https://example.com/releases/latest',
    })
    const state = useCoreUpdateState(rpc as never)

    await state.check()

    expect(rpc).toHaveBeenCalledWith('update.check', {})
    expect(state.status.value).toBe('update_available')
    expect(state.latestVersion.value).toBe('9.9.9')
    expect(state.downloadUrl.value).toContain('LamCore_9.9.9')
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

  it('wires the shared update state and startup banner in the demo App', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/demo/App.vue'), 'utf8')
    expect(source).toContain('useCoreUpdateState(requestConfigOperation)')
    expect(source).toContain(':update-state="updateState"')
    expect(source).toContain('data-update-banner')
    expect(source).toContain('readUpdateAutoCheck()')
  })
})
