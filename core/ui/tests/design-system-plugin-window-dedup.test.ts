import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import CorePluginSystemEditor from '../src/components/CorePluginSystemEditor.vue'
import { openPluginWindow } from '../src/helpers/pluginWindow'

vi.mock('../src/helpers/pluginWindow', () => ({ openPluginWindow: vi.fn(async () => true) }))

// user:“统一与去重”+(插件卡片和补充入口共用窗口数据和打开方式，保留没有卡片的窗口)。
it('shows each window once and uses the same desktop opener', async () => {
  const known = { plugin: 'alpha', id: 'main', title: '插件窗口 A', url: '/a', width: 400, height: 300 }
  const orphan = { plugin: 'other', id: 'main', title: '插件窗口 B', url: '/b', width: 500, height: 400 }
  const rpc = vi.fn(async (method: string) => method === 'plugin.system.list'
    ? { plugins: [{ name: 'alpha', enabled: true, version: '1', description: '', scope: 'global', root: '/a' }], errors: [] }
    : method === 'plugin.system.ui' ? { windows: [known, orphan] } : {})
  const wrapper = mount(CorePluginSystemEditor, { props: { requestRpc: rpc }, global: { stubs: { PluginSystemContributions: true } } })
  await flushPromises()
  expect(wrapper.findAll('button').filter(button => button.text().includes('插件窗口 A'))).toHaveLength(1)
  const fallback = wrapper.findAll('button').find(button => button.text() === '插件窗口 B')!
  expect(fallback).toBeTruthy()
  expect(rpc.mock.calls.filter(([method]) => method === 'plugin.system.ui')).toHaveLength(1)
  await wrapper.get('[data-window-for="alpha"]').trigger('click'); await fallback.trigger('click')
  expect(vi.mocked(openPluginWindow).mock.calls.map(([target]) => target)).toEqual([known, orphan])
  wrapper.unmount()
})

it('allows an isolated preview to handle window actions without opening a desktop window', async () => {
  const target = { plugin: 'other', id: 'main', title: '示例', url: '/example', width: 400, height: 300 }
  const rpc = vi.fn(async (method: string) => method === 'plugin.system.list' ? { plugins: [], errors: [] } : method === 'plugin.system.ui' ? { windows: [target] } : {})
  const previewOpen = vi.fn(async () => false)
  vi.mocked(openPluginWindow).mockClear()
  const wrapper = mount(CorePluginSystemEditor, { props: { requestRpc: rpc, openWindow: previewOpen }, global: { stubs: { PluginSystemContributions: true } } })
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '示例')!.trigger('click')
  expect(previewOpen).toHaveBeenCalledWith(target)
  expect(openPluginWindow).not.toHaveBeenCalled()
  wrapper.unmount()
})
