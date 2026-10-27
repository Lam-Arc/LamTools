import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import CorePluginSystemEditor from '../src/components/CorePluginSystemEditor.vue'
import { openPluginWindow, pluginWindowLabel } from '../src/helpers/pluginWindow'

const PLUGIN = {
  name: 'hello',
  version: '0.1.0',
  description: '',
  enabled: true,
  scope: 'global',
  root: '/plugins/hello',
}

const WINDOW = {
  plugin: 'hello',
  id: 'main',
  title: 'Hello 面板',
  url: '/api/core/plugin-system/hello/assets/window.html',
  width: 480,
  height: 320,
}

function makeRpc(windows: unknown[] = [WINDOW]) {
  return vi.fn(async (method: string) => {
    if (method === 'plugin.system.list') return { plugins: [PLUGIN], errors: [] }
    if (method === 'plugin.system.ui') return { styles: [], scripts: [], regions: [], windows }
    return {}
  })
}

function stubTauri() {
  const invoke = vi.fn(async () => undefined)
  ;(window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = { invoke }
  return invoke
}

const wrappers: Array<ReturnType<typeof mount>> = []

function mountEditor(rpc: ReturnType<typeof makeRpc>) {
  const wrapper = mount(CorePluginSystemEditor, { props: { requestRpc: rpc } })
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  while (wrappers.length) wrappers.pop()?.unmount()
  delete (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__
  vi.restoreAllMocks()
})

describe('plugin system windows', () => {
  it('opens a declared window through the desktop host', async () => {
    const invoke = stubTauri()
    const wrapper = mountEditor(makeRpc())
    await flushPromises()

    const button = wrapper.get('[data-window-for="hello"]')
    expect(button.text()).toContain('Hello 面板')
    await button.trigger('click')
    await flushPromises()

    expect(invoke).toHaveBeenCalledWith('open_plugin_window', {
      label: 'plugin-window:hello:main',
      url: '/api/core/plugin-system/hello/assets/window.html',
      title: 'Hello 面板',
      width: 480,
      height: 320,
    })
  })

  it('shows no window entry when nothing is declared', async () => {
    stubTauri()
    const wrapper = mountEditor(makeRpc([]))
    await flushPromises()

    expect(wrapper.find('[data-window-for]').exists()).toBe(false)
  })

  it('keeps working without a desktop host and reports the limitation', async () => {
    const wrapper = mountEditor(makeRpc())
    await flushPromises()

    await wrapper.get('[data-window-for="hello"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('插件窗口只能在桌面端打开')
  })

  it('sanitizes labels and skips hosts without an invoke bridge', async () => {
    expect(pluginWindowLabel({ plugin: 'my plugin', id: 'main view' })).toBe(
      'plugin-window:my-plugin:main-view',
    )
    expect(
      await openPluginWindow({ plugin: 'hello', id: 'main', url: '' }),
    ).toBe(false)
  })
})
