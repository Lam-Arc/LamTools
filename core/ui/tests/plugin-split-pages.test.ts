// user:“支持一下”+(验收独立挂载、上下文绑定、可见性及关闭清理)。
import { afterEach, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPluginPageInstance, pluginPageKey, type PluginPageContext } from '../src/plugins/pages'
import { useSplitWorkspace } from '../src/split/useSplitWorkspace'
import { restoreSplitState } from '../src/split/layout'
import * as pageModules from '../src/plugins/pages'
import { setPluginPageEntries } from '../src/plugins/contributions'
import CoreSplitPluginPage from '../src/components/CoreSplitPluginPage.vue'
import CorePluginSystemEditor from '../src/components/CorePluginSystemEditor.vue'
import CoreSplitWorkspace from '../src/components/CoreSplitWorkspace.vue'
import CoreSplitContent from '../src/components/CoreSplitContent.vue'
import { contextMenuState, closeContextMenu } from '../src/components/context-menu/context-menu'

afterEach(() => { setPluginPageEntries([]); closeContextMenu(); vi.restoreAllMocks(); localStorage.clear() })
const page = { plugin: 'demo', id: 'wall', title: 'Card wall', version: '1', entry_url: '/api/core/plugin-system/demo/assets/page.js' }

it('persists a plugin tab without changing the main mode or losing project scope', () => {
  let controller: ReturnType<typeof useSplitWorkspace>
  const root = ref('E:/first'), project = ref('first')
  const wrapper = mount(defineComponent({ setup() {
    controller = useSplitWorkspace(ref('plugin-test'), root, project)
    return () => h('div')
  } }))
  try {
    controller!.openPluginPage(page)
    root.value = 'E:/second'; project.value = 'second'
    const restored = restoreSplitState(JSON.stringify(controller!.state))
    const tab = Object.values(restored.panes)[0].tabs[0]
    expect(tab.kind).toBe('plugin')
    expect(tab.resource).toBe(pluginPageKey('demo', 'wall'))
    expect(tab.root).toBe('E:/first')
    expect(tab.projectId).toBe('first')
    // user:“支持一下”+(页面内部导航继承原标签上下文，不跟随主项目切换)。
    controller!.openPluginPage({ ...page, id: 'detail' }, undefined, { workRoot: tab.root!, projectId: tab.projectId })
    const detail = controller!.tabs.value.find(({ tab }) => tab.resource === pluginPageKey('demo', 'detail'))!.tab
    expect(detail.root).toBe('E:/first')
    expect(detail.projectId).toBe('first')
  } finally { wrapper.unmount() }
})

it('creates independent DOM, bound RPC scope and cleanup for two copies of one page', async () => {
  const contexts: PluginPageContext[] = [], cleanups = [vi.fn(), vi.fn()]
  const rpc = vi.fn(async () => ({}))
  const loader = vi.fn(async () => ({ mount(root: HTMLElement, context: PluginPageContext) {
    const index = contexts.length; contexts.push(context); root.textContent = context.instanceId
    return cleanups[index]
  } }))
  const first = document.createElement('div'), second = document.createElement('div')
  const a = createPluginPageInstance(first, page, { instanceId: 'a', workRoot: 'E:/a', projectId: 'a' }, rpc, { loadModule: loader })
  const b = createPluginPageInstance(second, page, { instanceId: 'b', workRoot: 'E:/b', projectId: 'b' }, rpc, { loadModule: loader })
  await Promise.all([a.ready, b.ready])
  expect(first.textContent).toBe('a'); expect(second.textContent).toBe('b')
  await contexts[0].rpc('demo.inspect', {})
  expect(rpc).toHaveBeenLastCalledWith('demo.inspect', expect.objectContaining({ work_root: 'E:/a', project_id: 'a' }))
  const visibility = vi.fn(); contexts[0].onVisibilityChange(visibility)
  a.setVisible(false)
  expect(visibility).toHaveBeenCalledWith(false)
  await a.dispose()
  expect(contexts[0].signal.aborted).toBe(true)
  expect(cleanups[0]).toHaveBeenCalledTimes(1)
  expect(cleanups[1]).not.toHaveBeenCalled()
  await expect(contexts[0].rpc('demo.inspect', {})).rejects.toThrow()
  await b.dispose()
})

it('cleans up a slow mount that finishes after the tab closes', async () => {
  let finish!: (cleanup: () => void) => void
  const cleanup = vi.fn(), host = document.createElement('div')
  const instance = createPluginPageInstance(host, page, { instanceId: 'late', workRoot: 'E:/a' }, vi.fn(async () => ({})), {
    loadModule: async () => ({ mount: () => new Promise<() => void>(resolve => { finish = resolve }) }),
  })
  await flushPromises()
  await instance.dispose()
  expect(host.children.length).toBe(0)
  finish(cleanup)
  await instance.ready
  expect(cleanup).toHaveBeenCalledTimes(1)
})

function pageRpc() {
  return vi.fn(async (method: string) => method === 'plugin.system.ui'
    ? { pages: [page], regions: [], windows: [] }
    : method === 'plugin.system.list' ? { plugins: [{ name: 'demo', version: '1', enabled: true, description: 'Demo' }] } : {})
}

it('unmounts live page instances when the plugin is disabled and can mount again', async () => {
  const cleanup = vi.fn(), contexts: PluginPageContext[] = []
  vi.spyOn(pageModules, 'loadPluginPageModule').mockResolvedValue({ mount(root, context) {
    contexts.push(context); root.textContent = 'Painted page'; return cleanup
  } })
  setPluginPageEntries([page])
  const wrapper = mount(CoreSplitPluginPage, { props: { tab: { id: 'live', kind: 'plugin', resource: pluginPageKey('demo', 'wall'), title: 'wall', root: 'E:/first' },
    workRoot: 'E:/other', visible: true, requestRpc: pageRpc() } })
  try {
    await flushPromises()
    expect(wrapper.text()).toContain('Painted page')
    expect(contexts).toHaveLength(1)
    setPluginPageEntries([])
    await flushPromises()
    expect(contexts[0].signal.aborted).toBe(true)
    expect(cleanup).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[role="alert"]').text()).toContain('禁用')
    setPluginPageEntries([page])
    await flushPromises()
    expect(contexts).toHaveLength(2)
    expect(contexts[1].workRoot).toBe('E:/first')
  } finally { wrapper.unmount(); await flushPromises() }
  expect(cleanup).toHaveBeenCalledTimes(2)
})

it('opens from the real plugin manager, appears in the split menu, and closes cleanly', async () => {
  const cleanup = vi.fn()
  vi.spyOn(pageModules, 'loadPluginPageModule').mockResolvedValue({ mount(root) { root.textContent = 'Standalone wall'; return cleanup } })
  const rpc = pageRpc()
  let controller!: ReturnType<typeof useSplitWorkspace>
  const wrapper = mount(defineComponent({ setup() {
    controller = useSplitWorkspace(ref('plugin-integration'), ref('E:/first'), ref('first'))
    return () => h('div', [h(CorePluginSystemEditor, { requestRpc: rpc }), h(CoreSplitWorkspace, { controller, workRoot: 'E:/first' }, {
      default: ({ tab, pane, visible }: any) => h(CoreSplitContent, { tab, pane, visible, controller, workRoot: 'E:/first',
        documents: {} as never, bindings: { plugins: { requestRpc: rpc } }, transport: {} as never, messages: [], activeSessionId: '',
        memberStatuses: {}, memberStatusRecords: {}, durableRecords: {}, memberWaitKnown: false, runningMemberNames: [], mainRunning: false }),
    })])
  } }), { global: { stubs: { PluginSystemContributions: true } } })
  try {
    await flushPromises()
    await wrapper.get('[data-open-plugin-page="wall"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Standalone wall')
    expect(controller.tabs.value[0].tab.kind).toBe('plugin')
    await wrapper.get('[aria-label="打开内容"]').trigger('click')
    const submenu = contextMenuState.items.find(item => item.type === 'submenu' && item.label === '插件页面')
    expect(submenu?.type === 'submenu' && submenu.children.some(item => 'label' in item && item.label.includes('Card wall'))).toBe(true)
    await wrapper.get('.split-tab-close').trigger('click')
    await flushPromises()
    expect(controller.tabs.value).toHaveLength(0)
    expect(cleanup).toHaveBeenCalledTimes(1)
  } finally { wrapper.unmount(); await flushPromises() }
})

it('runs the shipped card wall and stops polling while hidden or closed', async () => {
  const { readFileSync } = await import('node:fs')
  const { resolve } = await import('node:path')
  const { transpileModule, ModuleKind } = await import('typescript')
  const source = readFileSync(resolve(process.cwd(), '../../plugins/bili-scroll/ui/wall-page.mjs'), 'utf8')
  const compiled = transpileModule(source, { compilerOptions: { module: ModuleKind.CommonJS } })
  const module = {} as pageModules.PluginPageModule
  new Function('exports', compiled.outputText)(module)
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  const host = document.createElement('div')
  const rpc = vi.fn(async () => ({ reports: [], seen_recent: [{ bvid: 'BV12345678', title: 'Video title', up: 'Author' }] }))
  const instance = createPluginPageInstance(host, page, { instanceId: 'wall', workRoot: 'E:/demo' }, rpc, { loadModule: async () => module })
  try {
    await instance.ready; await flushPromises()
    expect(host.textContent).toContain('Video title')
    expect(vi.getTimerCount()).toBe(1)
    instance.setVisible(false)
    expect(vi.getTimerCount()).toBe(0)
    instance.setVisible(true)
    expect(vi.getTimerCount()).toBe(1)
  } finally { await instance.dispose(); vi.clearAllTimers(); vi.useRealTimers() }
  expect(host.children.length).toBe(0)
})
