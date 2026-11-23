// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import LamToolsApp from '@/app/LamToolsApp.vue'
import { createLamToolsRuntime } from '@/app/runtime'
import { createWorkspace, serializeWorkspace } from '@/workspace'
import type { LamToolsTransport, TransportRequest } from '@/transport'

// user:“中间消失了”+(Agent 侧栏点选会话后主区回到对话，已有文件标签仍可打开)。
it('returns to the selected chat from a restored file tab in the Agent layout', async () => {
  const key = 'lamtools.core.ui:split-workspace'
  const saved = createWorkspace([{ id: 'files-7', kind: 'file', title: 'Files', fileView: 'files' }], 'files-7')
  saved.prefs.layout = 'agent'
  localStorage.setItem(key, serializeWorkspace(saved))
  const transport: LamToolsTransport = {
    connect: async () => {},
    close: () => {},
    request: (async (req: TransportRequest) => {
      if (req.kind !== 'http') return {}
      const payload = req.path === '/projects' ? { projects: [{ id: 'project', name: 'Project', work_root: 'E:/example' }] }
        : req.path === '/sessions' ? [{ id: 'chat', title: 'Chat', project_id: 'project' }]
          : {}
      return { status: 200, headers: {}, body: new TextEncoder().encode(JSON.stringify(payload)) }
    }) as LamToolsTransport['request'],
    send: () => {},
    subscribe: () => () => {},
    onState: () => () => {},
    getState: () => 'connected',
  }
  const runtime = createLamToolsRuntime({
    transport,
    platform: 'desktop',
    capabilities: { filePicker: false, notifications: false, desktopWindow: false },
  })
  vi.stubGlobal('CSS', {})
  const scrollIntoView = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView')
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() })
  const wrapper = mount(LamToolsApp, { props: { runtime } })
  try {
    await flushPromises()
    expect(wrapper.find('.workspace-shell--main-replaced').exists()).toBe(true)
    await wrapper.get('[data-session-select="chat"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.workspace-shell--main-replaced').exists()).toBe(false)
    expect(wrapper.get('.thread').attributes('data-source-session-id')).toBe('chat')
    expect(wrapper.find('[data-region="composer"] [contenteditable]').exists()).toBe(true)
    window.dispatchEvent(new Event('pagehide'))
    expect(JSON.parse(localStorage.getItem(key)!).tree.area.tabs).toContain('files-7')
  } finally {
    wrapper.unmount()
    localStorage.removeItem(key)
    localStorage.removeItem(`${key}.prev`)
    vi.unstubAllGlobals()
    if (scrollIntoView) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', scrollIntoView)
    else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
  }
})
