// user:“实现这个插件，也正好实验我们的新插件架构”+(同一配置脚本加载中可被多个面板等待；卸载时释放自绘资源)。
import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import PluginConfigPanel from '../src/components/PluginConfigPanel.vue'

afterEach(() => { document.querySelectorAll('script[data-plugin-config-panel]').forEach(node => node.remove()); delete (window as any).LamToolsPluginPanels })
it('shares pending script loading and cleans both custom panels', async () => {
  const cleanups = [vi.fn(), vi.fn()], apis: any[] = []
  const mountPanel = vi.fn((_root: HTMLElement, api: any) => { apis.push(api); return cleanups[apis.length - 1] })
  const rpc = vi.fn(async () => ({ config: {}, schema: {}, has_panel: true, panel_url: '/test-network-panel.js' }))
  const props = { pluginName: 'network-test', version: '1', description: '', requestRpc: rpc }
  const a = mount(PluginConfigPanel, { props }), b = mount(PluginConfigPanel, { props })
  await flushPromises()
  expect(mountPanel).not.toHaveBeenCalled()
  ;(window as any).LamToolsPluginPanels = { 'network-test': { mount: mountPanel } }
  const script = document.querySelector('script[data-plugin-config-panel]')!
  script.dispatchEvent(new Event('load'))
  await flushPromises()
  expect(mountPanel).toHaveBeenCalledTimes(2)
  expect(apis.every(api => typeof api.rpc === 'function' && api.signal instanceof AbortSignal)).toBe(true)
  a.unmount(); b.unmount()
  expect(apis.every(api => api.signal.aborted)).toBe(true)
  expect(cleanups[0]).toHaveBeenCalledTimes(1); expect(cleanups[1]).toHaveBeenCalledTimes(1)
})
