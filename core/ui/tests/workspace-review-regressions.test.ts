// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, effectScope, h, nextTick, onUnmounted, ref } from 'vue'
import { expect, it, vi } from 'vitest'
import CoreSplitBrowser from '../src/components/CoreSplitBrowser.vue'
import CoreWorkspace from '../src/components/CoreWorkspace.vue'
import { useWorkspace } from '../src/workspace/useWorkspace'

// user:“快速精准高效的解决”+(用真实控制器验证恢复、关闭和跨位保活)。
it('restores the file type, scope and latest browser address', () => {
  vi.useFakeTimers()
  const key = ref('review-workspace-roundtrip')
  try {
    localStorage.removeItem(key.value)
    const scope = effectScope()
    const ws = scope.run(() => useWorkspace(key, ref('/project-a'), ref('a')))!
    const editor = ws.add('editor', 'notes.md', 'Notes', 'main', 'chat-a')!
    const fileTree = ws.add('files', '', 'File', 'main')!
    const browser = ws.add('browser', 'https://first.example', 'Browser', 'main')!
    ws.updateTabMetadata(browser.id, { resource: 'https://current.example', zoom: 1.25 })
    window.dispatchEvent(new Event('pagehide'))
    scope.stop()
    const restored = useWorkspace(key, ref('/project-b'), ref('b'))
    const tab = (id: string) => restored.tabs.value.find(entry => entry.tab.id === id)?.tab
    expect(tab(editor.id)).toMatchObject({ kind: 'editor', root: '/project-a', projectId: 'a', sessionId: 'chat-a' })
    expect(tab(fileTree.id)).toMatchObject({ kind: 'files', root: '/project-a' })
    expect(tab(browser.id)).toMatchObject({ resource: 'https://current.example', zoom: 1.25 })
  } finally {
    localStorage.removeItem(key.value)
    vi.useRealTimers()
  }
})

it('guards closing and removes a closed float from the persisted model', () => {
  const ws = useWorkspace(ref('review-close'), undefined, undefined, { persist: false })
  const editor = ws.add('editor', 'notes.md')!
  let confirm: (() => void) | undefined
  ws.registerGuard(editor.id, proceed => { confirm = proceed })
  ws.closeTab('main', editor)
  expect(ws.placementOf(editor.id)).not.toBeNull()
  expect(confirm).toBeTypeOf('function')
  confirm!()
  expect(ws.placementOf(editor.id)).toBeNull()
  const page = ws.add('browser', 'https://example.test')!
  ws.setSurfaceMode(page.id, 'float')
  ws.closeTab('float', page)
  expect(ws.model.value.floats.some(item => item.id === page.id)).toBe(false)
  expect(ws.model.value.surfaces[page.id]).toBeUndefined()
  const parked = ws.add('browser', 'https://parked.example')!
  ws.setSurfaceMode(parked.id, 'float')
  ws.collapseFloat(parked.id)
  ws.closeTab('parked', parked)
  expect(ws.parkedFloats.value).toHaveLength(0)
  expect(ws.model.value.surfaces[parked.id]).toBeUndefined()
})

it('keeps the whole pane until its tabs allow it to close', () => {
  const ws = useWorkspace(ref('review-pane'), undefined, undefined, { persist: false })
  const pane = ws.split('main', 'right')!
  const editor = ws.add('editor', 'notes.md', 'Notes', pane)!
  const other = ws.add('files', '', 'File', pane)!
  let allow: (() => void) | undefined
  ws.registerGuard(editor.id, proceed => { allow = proceed })
  ws.closePane(pane)
  expect(ws.state.panes[pane]?.tabs).toHaveLength(2)
  allow!()
  expect(ws.state.panes[pane]).toBeUndefined()
  // user:“更好的方式是折叠就等于关闭，这样可以通过右上角标签页抽屉直接再次将其显示出来”+
  // (关掉分屏不再销毁内容：两个标签都进「已收起」，抽屉里随时唤得回来)。
  expect(ws.model.value.surfaces[other.id]).toBeTruthy()
  expect(ws.parkedFloats.value.map(tab => tab.id)).toEqual(expect.arrayContaining([editor.id, other.id]))
})

it('moves the same mounted content between areas, float and parked state', async () => {
  const ws = useWorkspace(ref('review-move'), undefined, undefined, { persist: false })
  ws.setBounds({ x: 0, y: 0, width: 1200, height: 800 })
  const side = ws.split('main', 'right')!
  const page = ws.add('browser', 'https://example.test', 'Browser', side)!
  const unmounted = vi.fn()
  const View = defineComponent({ setup: () => {
    onUnmounted(unmounted)
    return () => h('input', { 'data-test-browser': '' })
  } })
  const wrapper = mount(CoreWorkspace, {
    attachTo: document.body, props: { controller: ws, workRoot: '' },
    slots: { default: ({ tab }: { tab: { id: string } }) => tab.id === page.id ? h(View) : null },
  })
  try {
    await nextTick()
    await nextTick()
    const input = document.querySelector<HTMLInputElement>('[data-test-browser]')!
    input.value = 'kept'
    ws.setSurfaceMode(page.id, 'float')
    await nextTick()
    await nextTick()
    expect(input.closest('[data-ws2-float]')?.getAttribute('data-ws2-float')).toBe(page.id)
    ws.collapseFloat(page.id)
    await nextTick()
    ws.reviveFloat(page.id)
    await nextTick()
    ws.setMain(page.id)
    await nextTick()
    await nextTick()
    expect(document.querySelector('[data-test-browser]')).toBe(input)
    expect(input.value).toBe('kept')
    expect(unmounted).not.toHaveBeenCalled()
  } finally { wrapper.unmount() }
})

it('moves the real browser component without closing or creating its native page again', async () => {
  const ws = useWorkspace(ref('review-native'), undefined, undefined, { persist: false })
  ws.setBounds({ x: 0, y: 0, width: 1200, height: 800 })
  const side = ws.split('main', 'right')!
  const page = ws.add('browser', 'https://example.test', 'Browser', side)!
  const call = vi.fn(async (_id: string, _action: string, _options?: Record<string, unknown>) => undefined)
  const services = { available: () => true, call, subscribe: async () => () => {}, openExternal: async () => {} }
  const wrapper = mount(CoreWorkspace, {
    attachTo: document.body, props: { controller: ws, workRoot: '' },
    slots: { default: (slot: { tab: typeof page; pane: string; visible: boolean }) => slot.tab.id === page.id
      ? h(CoreSplitBrowser, { ...slot, controller: ws, services }) : null },
  })
  const actions = () => call.mock.calls.map((args: unknown[]) => args[1])
  try {
    await flushPromises()
    expect(actions().filter(action => action === 'create')).toHaveLength(1)
    ws.setSurfaceMode(page.id, 'float')
    await flushPromises()
    ws.setMain(page.id)
    await flushPromises()
    expect(actions().filter(action => action === 'create')).toHaveLength(1)
    expect(actions()).not.toContain('close')
  } finally { wrapper.unmount() }
})
