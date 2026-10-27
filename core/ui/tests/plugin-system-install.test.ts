import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import CorePluginSystemEditor from '../src/components/CorePluginSystemEditor.vue'

function makeRpc() {
  const calls: Array<{ method: string; params?: Record<string, unknown> }> = []
  const rpc = vi.fn(async (method: string, params?: Record<string, unknown>) => {
    calls.push({ method, params })
    if (method === 'plugin.system.list') {
      return {
        plugins: [
          { name: 'demo', version: '1.0.0', enabled: true, scope: 'global', root: 'C:/p/demo' },
        ],
        errors: [],
      }
    }
    if (method === 'plugin.system.ui') return { styles: [], scripts: [], regions: [], windows: [], modes: [], errors: [] }
    if (method === 'plugin.deps-status') {
      return {
        name: 'demo',
        dependencies: [
          { name: 'json', status: 'ok' },
          { name: 'httpx', status: 'ok' },
        ],
        missing: 0,
      }
    }
    if (method === 'plugin.system.install' || method === 'plugin.system.update') {
      return {
        installed: method === 'plugin.system.install',
        updated: method === 'plugin.system.update',
        name: 'demo',
        dependencies: [
          { name: 'json', status: 'ok' },
          { name: 'no-such-pkg', status: 'missing' },
        ],
        missing_dependencies: 1,
      }
    }
    return {}
  })
  return { rpc, calls }
}

const wrappers: Array<ReturnType<typeof mount>> = []

function mountEditor(rpc: ReturnType<typeof makeRpc>['rpc']) {
  const wrapper = mount(CorePluginSystemEditor, { props: { requestRpc: rpc } })
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  while (wrappers.length) wrappers.pop()?.unmount()
  vi.restoreAllMocks()
})

describe('plugin system editor install surface', () => {
  it('opens the install tray and installs from a url with the dependency report', async () => {
    const { rpc, calls } = makeRpc()
    const wrapper = mountEditor(rpc)
    await flushPromises()

    const toggle = wrapper.get('[data-install-toggle]')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('.install-tray').exists()).toBe(true)
    expect(wrapper.find('form.preview-install').exists()).toBe(true)

    // 选择链接来源，填入地址与校验值后安装。
    const urlRadio = wrapper.find('input[type="radio"][value="url"]')
    await urlRadio.setValue()
    const target = wrapper.find('.install-input')
    await target.setValue('https://example.com/demo.zip')
    const sha = wrapper.find('.install-sha')
    await sha.setValue('deadbeef')
    const form = wrapper.find('form.preview-install')
    await form.trigger('submit')
    await flushPromises()

    const install = calls.find((call) => call.method === 'plugin.system.install')
    expect(install).toBeTruthy()
    expect(install!.params).toEqual({
      source: 'url',
      url: 'https://example.com/demo.zip',
      sha256: 'deadbeef',
    })
    // 缺包点名提示，但不阻止安装。
    expect(wrapper.text()).toContain('no-such-pkg')
    expect(wrapper.text()).toContain('已安装 demo')
  })

  it('updates through the same form with data kept', async () => {
    const { rpc, calls } = makeRpc()
    const wrapper = mountEditor(rpc)
    await flushPromises()

    await wrapper.get('[data-install-toggle]').trigger('click')
    await wrapper.find('input[type="radio"][value="zip"]').setValue()
    await wrapper.find('.install-input').setValue('C:/downloads/demo-2.zip')
    const updateButton = wrapper.get('[data-install-update]')
    expect(updateButton.text()).toContain('更新')
    await updateButton.trigger('click')
    await flushPromises()

    const update = calls.find((call) => call.method === 'plugin.system.update')
    expect(update).toBeTruthy()
    expect(update!.params).toEqual({ source: 'zip', path: 'C:/downloads/demo-2.zip' })
    expect(wrapper.text()).toContain('已更新 demo')
  })

  it('queries dependency status per plugin and shows the report in the card drawer', async () => {
    const { rpc, calls } = makeRpc()
    const wrapper = mountEditor(rpc)
    await flushPromises()

    const depsButton = wrapper.find('[data-deps-for="demo"]')
    await depsButton.trigger('click')
    await flushPromises()

    expect(calls.some((call) => call.method === 'plugin.deps-status' && call.params?.name === 'demo')).toBe(true)
    expect(wrapper.find('.preview-deps').text()).toContain('json:✓')
  })
})
