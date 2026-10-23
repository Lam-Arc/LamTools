import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import PluginConfigPanel from '../src/components/PluginConfigPanel.vue'

interface PanelApi {
  plugin: { name: string; version: string; description: string }
  config: Record<string, unknown>
  schema: Record<string, unknown>
  save: (values: Record<string, unknown>) => Promise<void>
}

const BASE_PAYLOAD = {
  name: 'hello',
  version: '0.1.0',
  description: 'demo plugin',
  config: {},
  schema: {},
  has_schema: false,
  panel_url: '',
  has_panel: false,
}

const SCHEMA = {
  type: 'object',
  properties: {
    endpoint: { type: 'string', title: '地址' },
    retries: { type: 'integer' },
    enabled: { type: 'boolean' },
    mode: { type: 'string', enum: ['fast', 'safe'] },
  },
}

function makeRpc(payload: Record<string, unknown> = BASE_PAYLOAD) {
  return vi.fn(async (method: string) => {
    if (method === 'plugin.system.config.get') return payload
    if (method === 'plugin.system.config.update') return {}
    return {}
  })
}

function propsFor(rpc: ReturnType<typeof makeRpc>) {
  return {
    pluginName: 'hello',
    version: '0.1.0',
    description: 'demo plugin',
    requestRpc: rpc,
  }
}

function clearPanelRegistry(): void {
  delete (window as unknown as { LamToolsPluginPanels?: unknown }).LamToolsPluginPanels
  document.head
    .querySelectorAll('script[data-plugin-config-panel]')
    .forEach((node) => node.remove())
}

afterEach(clearPanelRegistry)

describe('plugin config panel', () => {
  it('shows identity only for a plugin with nothing to configure', async () => {
    const wrapper = mount(PluginConfigPanel, { props: propsFor(makeRpc()) })
    await flushPromises()

    expect(wrapper.text()).toContain('hello')
    expect(wrapper.text()).toContain('0.1.0')
    expect(wrapper.text()).toContain('demo plugin')
    expect(wrapper.text()).toContain('这个插件没有可配置项')
    expect(wrapper.find('button[type="submit"]').exists()).toBe(false)
  })

  it('renders the schema form and saves typed values', async () => {
    const rpc = makeRpc({
      ...BASE_PAYLOAD,
      config: { endpoint: 'https://old.test' },
      schema: SCHEMA,
      has_schema: true,
    })
    const wrapper = mount(PluginConfigPanel, { props: propsFor(rpc) })
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('plugin.system.config.get', { name: 'hello' })
    const textInput = wrapper.find('input[type="text"]')
    await textInput.setValue('https://new.test')
    const numberInput = wrapper.find('input[type="number"]')
    await numberInput.setValue('3')
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await wrapper.find('select').setValue('safe')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('plugin.system.config.update', {
      name: 'hello',
      config: {
        endpoint: 'https://new.test',
        retries: 3,
        enabled: true,
        mode: 'safe',
      },
    })
    expect(wrapper.text()).toContain('已保存 hello 的配置')
  })

  it('mounts the author panel when the script registers itself', async () => {
    const mountSpy = vi.fn<(root: HTMLElement, api: PanelApi) => void>()
    ;(window as unknown as { LamToolsPluginPanels?: Record<string, unknown> })
      .LamToolsPluginPanels = { hello: { mount: mountSpy } }
    const rpc = makeRpc({
      ...BASE_PAYLOAD,
      has_panel: true,
      panel_url: '/api/core/plugin-system/hello/assets/config/panel.js',
    })
    const wrapper = mount(PluginConfigPanel, { props: propsFor(rpc) })
    await flushPromises()

    const script = document.head.querySelector<HTMLScriptElement>(
      'script[data-plugin-config-panel]',
    )
    expect(script).not.toBeNull()
    script!.dispatchEvent(new Event('load'))
    await flushPromises()

    expect(mountSpy).toHaveBeenCalledTimes(1)
    const [root, api] = mountSpy.mock.calls[0]
    expect(root).toBeTruthy()
    expect(api.plugin.name).toBe('hello')
    expect(wrapper.find('form').exists()).toBe(false)

    await api.save({ custom: true })
    expect(rpc).toHaveBeenCalledWith('plugin.system.config.update', {
      name: 'hello',
      config: { custom: true },
    })
  })

  it('falls back to the default form when the panel never registers', async () => {
    const rpc = makeRpc({
      ...BASE_PAYLOAD,
      schema: SCHEMA,
      has_schema: true,
      has_panel: true,
      panel_url: '/api/core/plugin-system/hello/assets/config/panel.js',
    })
    const wrapper = mount(PluginConfigPanel, { props: propsFor(rpc) })
    await flushPromises()

    document.head
      .querySelector('script[data-plugin-config-panel]')
      ?.dispatchEvent(new Event('load'))
    await flushPromises()

    expect(wrapper.find('form').exists()).toBe(true)
    expect(wrapper.text()).toContain('地址')
  })

  it('reports a failed script load and keeps the default form', async () => {
    const rpc = makeRpc({
      ...BASE_PAYLOAD,
      schema: SCHEMA,
      has_schema: true,
      has_panel: true,
      panel_url: '/api/core/plugin-system/hello/assets/config/panel.js',
    })
    const wrapper = mount(PluginConfigPanel, { props: propsFor(rpc) })
    await flushPromises()

    document.head
      .querySelector('script[data-plugin-config-panel]')
      ?.dispatchEvent(new Event('error'))
    await flushPromises()

    expect(wrapper.text()).toContain('自定义配置面板加载失败')
    expect(wrapper.find('form').exists()).toBe(true)
  })
})
