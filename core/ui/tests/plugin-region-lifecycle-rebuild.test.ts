// user:“该调的模块就是该写的东西”+(区域自绘与分屏共用 mount/cleanup 生命周期)。
import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
const hooks = vi.hoisted(() => ({ cleanup: vi.fn(), start: vi.fn() }))
vi.mock('../src/plugins/pages', async original => {
  const actual = await original<typeof import('../src/plugins/pages')>()
  return { ...actual, loadPluginPageModule: vi.fn(async () => ({ mount: (root: HTMLElement) => {
    root.textContent = '已挂载'; hooks.start(); return hooks.cleanup
  } })) }
})
import PluginRegionEntry from '../src/components/PluginRegionEntry.vue'

it('mounts each region instance and cleans it up on removal', async () => {
  const wrapper = mount(PluginRegionEntry, { props: { plugin: 'demo', entryUrl: '/api/core/plugin-system/demo/assets/main.mjs', requestRpc: vi.fn(async () => ({})) } })
  await flushPromises()
  expect(wrapper.text()).toContain('已挂载')
  expect(hooks.start).toHaveBeenCalledOnce()
  wrapper.unmount()
  await flushPromises()
  expect(hooks.cleanup).toHaveBeenCalledOnce()
})
