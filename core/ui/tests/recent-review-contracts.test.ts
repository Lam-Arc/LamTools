// user:“该修修”+(验证 Wiki 实际接入和插件桥更新，不只检查组件存在)。
import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import LibraryHomeView from '../src/components/LibraryHomeView.vue'
import { setContributionsRpc } from '../src/plugins/contributions'
import OperationTrustSettings from '../src/components/OperationTrustSettings.vue'
import { coreAppServerDecision } from '../src/appServer/workbenchActions'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
const board = readFileSync(resolve(process.cwd(), '../../plugins/bili-scroll/ui/board.js'), 'utf8')

afterEach(() => { setContributionsRpc(null); vi.restoreAllMocks() })

it('sends explicit trust through the real decision mapper', () => {
  expect(coreAppServerDecision('trust')).toBe('trust')
})

it('shows persistent trust and allows revocation from settings', async () => {
  const key = JSON.stringify(['E:/work', 'run_command', 'git reset --hard'])
  let entries = [{ key, level: 2 }]
  const rpc = vi.fn(async (method: string) => {
    if (method === 'permissions.trust.revoke') { entries = []; return { revoked: true } }
    return { entries }
  })
  const wrapper = mount(OperationTrustSettings, { props: { requestRpc: rpc } })
  try {
    await flushPromises()
    expect(wrapper.text()).toContain('git reset --hard')
    await wrapper.get('[data-trust-revoke]').trigger('click')
    await flushPromises()
    expect(rpc).toHaveBeenCalledWith('permissions.trust.revoke', { key })
    expect(wrapper.find('[data-trust-revoke]').exists()).toBe(false)
  } finally { wrapper.unmount() }
})

it('opens the bundled wiki from the real library tab', async () => {
  const rpc = vi.fn(async (method: string) => method === 'library.wiki.list'
    ? { articles: [{ slug: 'articles/help', title: 'Bundled help', summary: '', section: '', size: 1 }] }
    : { title: 'Bundled help', content: '# Read me' })
  const wrapper = mount(LibraryHomeView, { props: { client: {} as never, requestRpc: rpc },
    global: { stubs: { MaterialsView: true, MemoryView: true, PlanLibraryView: true, MarkdownRenderer: true } } })
  try {
    await wrapper.get('[data-library-section="wiki"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Bundled help')
    await wrapper.get('.wiki-row').trigger('click')
    await flushPromises()
    expect(rpc).toHaveBeenCalledWith('library.wiki.read', { slug: 'articles/help' })
  } finally { wrapper.unmount() }
})

it('refreshes and clears the global plugin RPC bridge', () => {
  const first = vi.fn(async () => ({}))
  const second = vi.fn(async () => ({}))
  setContributionsRpc(first)
  expect(window.LamToolsPluginRPC).toBe(first)
  setContributionsRpc(second)
  expect(window.LamToolsPluginRPC).toBe(second)
  setContributionsRpc(null)
  expect(window.LamToolsPluginRPC).toBeUndefined()
})

it('mounts the plain JavaScript card wall after its script has loaded', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  const observers: MutationObserver[] = []
  const Observer = MutationObserver
  vi.stubGlobal('MutationObserver', class extends Observer {
    constructor(callback: MutationCallback) { super(callback); observers.push(this) }
  })
  window.LamToolsPluginRPC = vi.fn(async () => ({ reports: [], seen_recent: [] }))
  try {
    new Function(board)()
    const first = document.createElement('div')
    first.dataset.pluginEntry = 'bili-scroll'
    document.body.append(first)
    await flushPromises()
    expect(first.textContent).toContain('还没有记录')
    expect(vi.getTimerCount()).toBe(1)
    first.remove()
    await flushPromises()
    expect(vi.getTimerCount()).toBe(0)
    const replacement = document.createElement('div')
    replacement.dataset.pluginEntry = 'bili-scroll'
    document.body.append(replacement)
    await flushPromises()
    expect(replacement.textContent).toContain('还没有记录')
    replacement.remove()
  } finally {
    observers.forEach(observer => observer.disconnect())
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  }
})
